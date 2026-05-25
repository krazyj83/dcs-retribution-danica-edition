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
from typing import TYPE_CHECKING, Iterator

from dcs.mapping import Point
from game.theater.missiontarget import MissionTarget

if TYPE_CHECKING:
    from game.ato.flighttype import FlightType
    from game.theater import Coalition, Player


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
    position: Point          # midpoint — used by flight plan builder
    start: Point = field(default=None)
    end: Point = field(default=None)
    _coalition: object = field(default=None, repr=False)

    def is_friendly(self, to_player: Player) -> bool:
        # The convoy route is always a friendly asset — it's the player's supply line.
        return True

    @property
    def coalition(self) -> Coalition:
        return self._coalition

    def mission_types(self, for_player: Player) -> Iterator[FlightType]:
        """Yield mission types suitable for protecting a player convoy route.

        CONVOY_ESCORT is an independent FlightType (not ESCORT or SEAD_ESCORT)
        so it bypasses the package dialog's 'only escort flights' validation.
        CAS and BARCAP are offered as alternatives.
        """
        from game.ato.flighttype import FlightType
        yield FlightType.CONVOY_ESCORT
        yield FlightType.CAS
        yield FlightType.BARCAP
