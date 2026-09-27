"""Spawns vehicle convoys on player-drawn convoy routes for the current mission.

Each convoy borrows real vehicles from a friendly base's spare reserve:

- Source: the friendly base nearest the route start that has spare vehicles,
  falling back outward to the next nearest.
- Spare: the base's reserve (armor not deployed to the front line, see
  ``reserve_armor_for``) minus vehicles already parked in its motorpools this
  mission, minus vehicles earlier convoys in this mission already took.
- Mix: up to ``CONVOY_SIZE`` vehicles, taken round-robin across the base's most
  plentiful types, so a convoy is e.g. 2 trucks + 1 APC + 1 tank.
- Destination: the friendly base nearest the route end.

Every vehicle is registered in the UnitMap. After the mission,
``MissionResultsProcessor.commit_player_drawn_convoys`` removes dead vehicles
from the source base and delivers survivors to the destination base.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from typing import TYPE_CHECKING

from dcs import Mission
from dcs.mapping import LatLng, Point
from dcs.point import PointAction
from dcs.unitgroup import VehicleGroup

from game.dcs.groundunittype import GroundUnitType
from game.ground_forces.ai_ground_planner import reserve_armor_for
from game.missiongenerator.groundforcepainter import GroundForcePainter
from game.theater.player import Player
from game.theater.theatergroundobject import MotorpoolGroundObject
from game.utils import kph

if TYPE_CHECKING:
    from game import Game
    from game.theater.convoyroute import PlayerConvoyRoute
    from game.theater import ControlPoint
    from game.unitmap import UnitMap

logger = logging.getLogger(__name__)

# Maximum number of vehicles per player convoy.
CONVOY_SIZE = 4

# 40 km/h is realistic for a road-bound supply column.
CONVOY_SPEED = kph(40).kph

# pydcs spaces a new group's units 20 m apart along Y; extra types continue that.
_UNIT_SPACING_M = 20


class PlayerConvoyGenerator:
    """Generates vehicle groups on player-drawn convoy routes."""

    def __init__(self, mission: Mission, game: Game, unit_map: UnitMap) -> None:
        self.mission = mission
        self.game = game
        self.unit_map = unit_map
        self._counter = itertools.count(1)
        # Vehicles already taken by earlier convoys this mission, per base.
        self._taken: dict[ControlPoint, Counter[GroundUnitType]] = {}

    def generate(self) -> None:
        routes = getattr(self.game, "player_convoy_routes", {})
        for route in list(routes.values()):
            try:
                self._spawn_convoy(route)
            except Exception:
                logger.exception(
                    f"Failed to generate player convoy for route '{route.name}'"
                )

    def _spawn_convoy(self, route: PlayerConvoyRoute) -> None:
        """Create one vehicle group driving the given route."""
        terrain = self.game.theater.terrain
        start = Point.from_latlng(LatLng(route.start_lat, route.start_lng), terrain)
        end = Point.from_latlng(LatLng(route.end_lat, route.end_lng), terrain)

        friendly = [
            cp
            for cp in self.game.theater.controlpoints
            if cp.captured is Player.BLUE and cp.can_deploy_ground_units
        ]
        if not friendly:
            logger.warning(f"No friendly base for player convoy '{route.name}'")
            return

        origin, units = self._find_source(friendly, start)
        if origin is None:
            logger.warning(
                f"Skipping player convoy '{route.name}': no friendly base has "
                "spare vehicles"
            )
            return
        destination = min(friendly, key=lambda cp: cp.position.distance_to_point(end))

        self._taken.setdefault(origin, Counter()).update(units)

        group_name = f"Player Convoy {next(self._counter)} - {route.name}"
        group, unit_types = self._create_group(group_name, start, units)
        group.add_waypoint(end, speed=CONVOY_SPEED, move_formation=PointAction.OnRoad)
        # Allow Combined Arms players to drive convoy vehicles.
        for unit in group.units:
            unit.player_can_drive = True

        self.unit_map.add_player_drawn_convoy_units(
            group, unit_types, origin, destination
        )
        logger.info(
            f"Spawned '{group_name}': {len(unit_types)} vehicles from {origin} "
            f"to {destination}"
        )

    def _find_source(
        self, friendly: list[ControlPoint], start: Point
    ) -> tuple[ControlPoint | None, dict[GroundUnitType, int]]:
        """The nearest friendly base to ``start`` with spare vehicles."""
        for cp in sorted(friendly, key=lambda c: c.position.distance_to_point(start)):
            units = self._pick_units(self._spare_units(cp))
            if units:
                return cp, units
        return None, {}

    def _spare_units(self, cp: ControlPoint) -> dict[GroundUnitType, int]:
        """Reserve armor not parked in a motorpool nor taken by another convoy."""
        parked: Counter[GroundUnitType] = Counter()
        for tgo in cp.ground_objects:
            if not isinstance(tgo, MotorpoolGroundObject):
                continue
            for group in tgo.groups:
                unit_type = tgo.motorpool_unit_types.get(group.id)
                if unit_type is not None:
                    parked[unit_type] += len(group.units)

        taken = self._taken.get(cp, Counter())
        spare: dict[GroundUnitType, int] = {}
        for unit_type, count in reserve_armor_for(cp).items():
            remaining = count - parked[unit_type] - taken[unit_type]
            if remaining > 0:
                spare[unit_type] = remaining
        return spare

    @staticmethod
    def _pick_units(spare: dict[GroundUnitType, int]) -> dict[GroundUnitType, int]:
        """Up to CONVOY_SIZE vehicles, round-robin over the most plentiful types."""
        remaining = dict(
            sorted(spare.items(), key=lambda item: (-item[1], str(item[0])))
        )
        picked: Counter[GroundUnitType] = Counter()
        while remaining and sum(picked.values()) < CONVOY_SIZE:
            for unit_type in list(remaining):
                if sum(picked.values()) >= CONVOY_SIZE:
                    break
                picked[unit_type] += 1
                remaining[unit_type] -= 1
                if remaining[unit_type] == 0:
                    del remaining[unit_type]
        return dict(picked)

    def _create_group(
        self, name: str, position: Point, units: dict[GroundUnitType, int]
    ) -> tuple[VehicleGroup, list[GroundUnitType]]:
        """A mixed-type vehicle group; the list gives each unit's type in order."""
        faction = self.game.coalition_for(Player.BLUE).faction
        country = self.mission.country(faction.country.name)

        unit_types = list(units.items())
        main_type, main_count = unit_types[0]
        group = self.mission.vehicle_group(
            country,
            name,
            main_type.dcs_unit_type,
            position=position,
            group_size=main_count,
            move_formation=PointAction.OnRoad,
        )
        types_in_order = [main_type] * main_count

        unit_number = itertools.count(main_count + 1)
        y = itertools.count(position.y + main_count * _UNIT_SPACING_M, _UNIT_SPACING_M)
        for unit_type, count in unit_types[1:]:
            for _ in range(count):
                vehicle = self.mission.vehicle(
                    f"{name} Unit #{next(unit_number)}", unit_type.dcs_unit_type
                )
                vehicle.position.x = position.x
                vehicle.position.y = next(y)
                vehicle.heading = 0
                GroundForcePainter(faction, vehicle).apply_livery()
                group.add_unit(vehicle)
                types_in_order.append(unit_type)
        return group, types_in_order
