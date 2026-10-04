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

Every vehicle is registered in the UnitMap. The mission script
(resources/plugins/base/dcs_retribution.lua) watches each convoy and records
the vehicles that get within ``ARRIVAL_RADIUS_M`` of the route end. After the
mission, ``MissionResultsProcessor.commit_player_drawn_convoys`` removes dead
vehicles from the source base and delivers only the vehicles that arrived to
the destination base; the rest stay at the source base.

Cargo trucks: every convoy also gets up to CARGO_TRUCKS_PER_CONVOY of the
faction's cargo trucks, behind the borrowed vehicles. They aren't taken from
a base; they haul ammunition and supplies from the source base's warehouse
(see logistics/convoy_cargo.py). A route with no spare vehicles still gets a
convoy of trucks, from the friendly base nearest its start.

Escort hold: a route with a Convoy Escort flight planned on it waits at its
start (a Hold task stopped by a flag) until an aircraft of that flight is
airborne within ESCORT_RADIUS_M of the start, or for ESCORT_WAIT_S at most.
The mission script sets the flag (dcs_retribution.lua).
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from dcs import Mission
from dcs.mapping import LatLng, Point
from dcs.point import PointAction
from dcs.task import ControlledTask, Hold
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

# A vehicle within this distance of the route end has arrived. Road-bound
# columns stop at the road point nearest the end, which can be off the exact
# spot the player clicked.
ARRIVAL_RADIUS_M = 2000

# pydcs spaces a new group's units 20 m apart along Y; extra types continue that.
_UNIT_SPACING_M = 20

# A convoy with an escort flight waits until an escort aircraft is within this
# distance of its start (5 nm) ...
ESCORT_RADIUS_M = 9260
# ... or this long after mission start, then drives on alone.
ESCORT_WAIT_S = 3600


class PlayerConvoyGenerator:
    """Generates vehicle groups on player-drawn convoy routes."""

    def __init__(self, mission: Mission, game: Game, unit_map: UnitMap) -> None:
        self.mission = mission
        self.game = game
        self.unit_map = unit_map
        self._counter = itertools.count(1)
        # Vehicles already taken by earlier convoys this mission, per base.
        self._taken: dict[ControlPoint, Counter[GroundUnitType]] = {}
        # Group name and route end of each spawned convoy, for the mission script.
        self._spawned: list[dict[str, Any]] = []
        # Escort flights of each held convoy, by group name.
        self._escorts: dict[str, list[Any]] = {}

    def script_data(self, unit_map: UnitMap | None = None) -> dict[str, Any]:
        """The table the mission script uses to detect arrivals and to release
        held convoys. Escort unit names need the aircraft generated (unit_map).
        """
        convoys = []
        for convoy in self._spawned:
            entry = dict(convoy)
            flights = self._escorts.get(convoy["group"], [])
            if flights and unit_map is not None:
                entry["escorts"] = sorted(
                    name
                    for name, unit in unit_map.aircraft.items()
                    if unit.flight in flights
                )
            convoys.append(entry)
        return {
            "radius": ARRIVAL_RADIUS_M,
            "escortRadius": ESCORT_RADIUS_M,
            "escortWait": ESCORT_WAIT_S,
            "convoys": convoys,
        }

    def _escort_flights(self, route: PlayerConvoyRoute) -> list[Any]:
        """Convoy Escort flights planned on this route."""
        from game.ato.flighttype import FlightType
        from game.theater.convoyroute import ConvoyRouteTarget

        flights: list[Any] = []
        ato = getattr(self.game.coalition_for(Player.BLUE), "ato", None)
        for package in getattr(ato, "packages", None) or []:
            target = package.target
            if not isinstance(target, ConvoyRouteTarget):
                continue
            route_id = getattr(target, "route_id", None)
            if route_id is not None and route_id != route.id:
                continue
            if route_id is None and target.name != route.name:
                continue
            flights.extend(
                f for f in package.flights if f.flight_type is FlightType.CONVOY_ESCORT
            )
        return flights

    def generate(self) -> None:
        from game.logistics.convoy_cargo import start_mission

        start_mission(self.game)
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

        from game.logistics.convoy_cargo import (
            CARGO_TRUCKS_PER_CONVOY,
            cargo_truck_type,
            register,
        )

        truck_type = cargo_truck_type(self.game.coalition_for(Player.BLUE).faction)
        trucks = CARGO_TRUCKS_PER_CONVOY if truck_type is not None else 0

        origin, units = self._find_source(friendly, start)
        if origin is None:
            if not trucks:
                logger.warning(
                    f"Skipping player convoy '{route.name}': no friendly base has "
                    "spare vehicles"
                )
                return
            # Trucks only, from the friendly base nearest the start.
            origin = min(friendly, key=lambda cp: cp.position.distance_to_point(start))
            units = {}
        destination = min(friendly, key=lambda cp: cp.position.distance_to_point(end))

        self._taken.setdefault(origin, Counter()).update(units)

        number = next(self._counter)
        group_name = f"Player Convoy {number} - {route.name}"
        entries = list(units.items())
        if truck_type is not None and trucks:
            entries.append((truck_type, trucks))
        group, unit_types = self._create_group(group_name, start, entries)
        borrowed = sum(units.values())

        escorts = self._escort_flights(route)
        flag = None
        if escorts:
            flag = f"convoy-go-{number}"
            hold = ControlledTask(Hold())
            hold.stop_if_user_flag(flag, True)
            hold.stop_after_duration(ESCORT_WAIT_S)
            group.points[0].tasks.append(hold)
            self._escorts[group_name] = escorts

        group.add_waypoint(end, speed=CONVOY_SPEED, move_formation=PointAction.OnRoad)
        # Allow Combined Arms players to drive convoy vehicles.
        for unit in group.units:
            unit.player_can_drive = True

        if borrowed:
            self.unit_map.add_player_drawn_convoy_units(
                group, unit_types[:borrowed], origin, destination, count=borrowed
            )
        register(
            self.game,
            [str(u.name) for u in group.units[borrowed:]],
            origin,
            destination,
        )
        entry: dict[str, Any] = {"group": group_name, "x": end.x, "z": end.y}
        if flag is not None:
            entry.update(flag=flag, startX=start.x, startZ=start.y, label=route.name)
        self._spawned.append(entry)
        logger.info(
            f"Spawned '{group_name}': {borrowed} vehicles and "
            f"{len(unit_types) - borrowed} cargo trucks from {origin} to "
            f"{destination}"
            + (f", waiting for {len(escorts)} escort flight(s)" if escorts else "")
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
        """Up to CONVOY_SIZE vehicles, round-robin over the most plentiful types,
        plus up to MAX_FUEL_TRUCKS_PER_CONVOY fuel trucks when the base has
        spare ones (they deliver fuel, see logistics/fuel.py)."""
        from game.logistics.fuel import MAX_FUEL_TRUCKS_PER_CONVOY, is_fuel_truck

        trucks: Counter[GroundUnitType] = Counter()
        for unit_type, count in sorted(
            spare.items(), key=lambda item: (-item[1], str(item[0]))
        ):
            if not is_fuel_truck(unit_type):
                continue
            take = min(count, MAX_FUEL_TRUCKS_PER_CONVOY - sum(trucks.values()))
            if take > 0:
                trucks[unit_type] += take
        remaining = dict(
            sorted(
                ((t, n) for t, n in spare.items() if not is_fuel_truck(t)),
                key=lambda item: (-item[1], str(item[0])),
            )
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
        picked.update(trucks)
        return dict(picked)

    def _create_group(
        self,
        name: str,
        position: Point,
        units: list[tuple[GroundUnitType, int]] | dict[GroundUnitType, int],
    ) -> tuple[VehicleGroup, list[GroundUnitType]]:
        """A mixed-type vehicle group; the list gives each unit's type in order."""
        faction = self.game.coalition_for(Player.BLUE).faction
        country = self.mission.country(faction.country.name)

        unit_types = list(units.items()) if isinstance(units, dict) else list(units)
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
