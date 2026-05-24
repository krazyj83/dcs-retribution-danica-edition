"""Spawns vehicle convoys on player-drawn convoy routes for the current mission.

Concepts used:
- game.coalition_for(Player.BLUE): resolves the blue coalition object.
- faction.frontline_units: the Set[GroundUnitType] the faction can field.
  We pick from this so the convoy uses faction-appropriate vehicles.
- mission.vehicle_group(): pydcs call that creates a DCS ground unit group.
- group.add_waypoint(..., move_formation=PointAction.OnRoad): DCS AI follows
  roads between waypoints rather than driving cross-country.
"""
from __future__ import annotations

import itertools
import logging
import random
from typing import TYPE_CHECKING

from dcs import Mission
from dcs.mapping import LatLng, Point
from dcs.point import PointAction

from game.server.convoyroutes.routes import get_all as get_all_convoy_routes
from game.theater.player import Player
from game.utils import kph

if TYPE_CHECKING:
    from game import Game

logger = logging.getLogger(__name__)

# Number of vehicles per player convoy.
CONVOY_SIZE = 4

# 40 km/h is realistic for a road-bound supply column.
CONVOY_SPEED = kph(40).kph


class PlayerConvoyGenerator:
    """Generates vehicle groups on player-drawn convoy routes."""

    def __init__(self, mission: Mission, game: Game) -> None:
        self.mission = mission
        self.game = game
        self._counter = itertools.count(1)

    def generate(self) -> None:
        routes = get_all_convoy_routes()
        if not routes:
            return

        for route in routes:
            try:
                self._spawn_convoy(route)
            except Exception:
                logger.exception(
                    f"Failed to generate player convoy for route '{route.name}'"
                )

    def _spawn_convoy(self, route) -> None:
        """Create one vehicle group driving the given ConvoyRouteJs."""
        terrain = self.game.theater.terrain

        start = Point.from_latlng(
            LatLng(route.start.lat, route.start.lng), terrain
        )
        end = Point.from_latlng(
            LatLng(route.end.lat, route.end.lng), terrain
        )

        # coalition_for(Player.BLUE) matches how convoygenerator.py resolves
        # the faction — Player is an enum with BLUE, RED, NEUTRAL values.
        blue_coalition = self.game.coalition_for(Player.BLUE)
        faction = blue_coalition.faction
        country = self.mission.country(faction.country.name)

        available_units = list(faction.frontline_units)
        if not available_units:
            logger.warning(
                f"Faction '{faction.name}' has no frontline units; "
                f"skipping player convoy '{route.name}'"
            )
            return

        unit_type = random.choice(available_units)
        group_name = f"Player Convoy {next(self._counter)} - {route.name}"

        logger.debug(
            f"Spawning '{group_name}' ({unit_type.name} x{CONVOY_SIZE})"
        )

        group = self.mission.vehicle_group(
            country,
            group_name,
            unit_type.dcs_unit_type,
            position=start,
            group_size=CONVOY_SIZE,
            move_formation=PointAction.OnRoad,
        )

        group.add_waypoint(
            end,
            speed=CONVOY_SPEED,
            move_formation=PointAction.OnRoad,
        )

        # Allow Combined Arms players to drive convoy vehicles.
        for unit in group.units:
            unit.player_can_drive = True
