"""Mission target for player-drawn convoy routes.

A ConvoyRouteTarget wraps a ConvoyRouteJs (from the server store) into a
MissionTarget so it can be passed to qt.create_new_package(), which opens
the standard New Package dialog. The dialog will offer CONVOY_ESCORT as an
independent mission type — not subject to the "only escort flights" validation
— along with CAS and BARCAP as alternatives.

The target position is set to the route midpoint so the flight plan builder
places the orbit over the centre of the route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Iterator, Optional
from uuid import UUID

from dcs.mapping import Point
from game.theater.missiontarget import MissionTarget

if TYPE_CHECKING:
    from game.ato.flighttype import FlightType
    from game.theater import Coalition, Player
    from game.utils import Distance

#: Same drive-time estimate as the map (client/.../dropzonelayer/convoyTime.ts):
#: the road is 1.2 to 1.5 times the straight line, driven at 40 km/h.
CONVOY_SPEED_KPH = 40.0
ROAD_FACTOR_LOW = 1.2
ROAD_FACTOR_HIGH = 1.5


def drive_time(straight_line: Distance) -> tuple[timedelta, timedelta]:
    """(fastest, slowest) estimated drive time for a route this long."""
    hours = straight_line.kilometers / CONVOY_SPEED_KPH
    return (
        timedelta(hours=hours * ROAD_FACTOR_LOW),
        timedelta(hours=hours * ROAD_FACTOR_HIGH),
    )


@dataclass
class PlayerConvoyRoute:
    """A convoy route drawn on the map by the player.

    Saved with the campaign (``Game.player_convoy_routes``). A convoy drives
    the route in the next mission. A one-off route is removed when the turn
    ends; a standing route (``repeat``) stays, and a new convoy drives it every
    turn until the player removes it.

    ``via``: waypoints between start and end, (lat, lng), in driving order.
    The convoy drives start -> each waypoint -> end, on roads.
    """

    id: UUID
    name: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    repeat: bool = False
    via: list[tuple[float, float]] = field(default_factory=list)

    def __setstate__(self, state: dict[str, Any]) -> None:
        # Routes saved before standing routes existed were all one-off, and
        # routes saved before waypoints went straight from start to end.
        state.setdefault("repeat", False)
        state.setdefault("via", [])
        self.__dict__.update(state)

    @property
    def points(self) -> list[tuple[float, float]]:
        """Start, waypoints and end, (lat, lng)."""
        return [
            (self.start_lat, self.start_lng),
            *[(float(lat), float(lng)) for lat, lng in self.via],
            (self.end_lat, self.end_lng),
        ]


@dataclass
class ConvoyRouteTarget(MissionTarget):
    """A player-defined ground supply route that can be protected from the air.

    Attributes:
        name:       Display name (e.g. "MSR Alpha").
        position:   DCS Point at the midpoint of the route.
        start:      DCS Point for route start.
        end:        DCS Point for route end.
        _coalition: The coalition that owns (and wants to protect) this route.
    """

    name: str
    position: Point  # midpoint — used by flight plan builder
    start: Optional[Point] = None
    end: Optional[Point] = None
    _coalition: Any = field(default=None, repr=False)
    #: The PlayerConvoyRoute this target was made for (None in older saves:
    #: matched by name instead).
    route_id: Optional[UUID] = None
    #: The route's waypoints between start and end, in driving order.
    via: list[Point] = field(default_factory=list)

    @property
    def path(self) -> list[Point]:
        """Start, waypoints and end (empty without start or end)."""
        if self.start is None or self.end is None:
            return []
        return [self.start, *getattr(self, "via", []), self.end]

    @property
    def path_length(self) -> Distance:
        """Straight-line length of the route, leg by leg."""
        from game.utils import meters

        path = self.path
        return meters(sum(a.distance_to_point(b) for a, b in zip(path, path[1:])))

    def is_friendly(self, to_player: Player) -> bool:
        # The convoy route is always a friendly asset — it's the player's supply line.
        return True

    @property
    def coalition(self) -> Coalition:
        return self._coalition

    def mission_types(self, for_player: Player) -> Iterator[FlightType]:
        """Yield mission types suitable for protecting a player convoy route.

        CONVOY_ESCORT (game/ato/flightplans/convoyescort.py) patrols the road
        from start to end for the convoy's drive time, attacking ground units
        near it; it is a main task, not an escort of other flights. BARCAP
        covers the route from the air.
        """
        from game.ato.flighttype import FlightType

        yield FlightType.CONVOY_ESCORT
        yield FlightType.BARCAP
