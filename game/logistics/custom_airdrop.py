"""A map point players can plan air assault, transport and logistic flights to."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator, Optional

from dcs.mapping import Point

from game.theater.missiontarget import MissionTarget

if TYPE_CHECKING:
    from game.ato.flighttype import FlightType
    from game.coalition import Coalition
    from game.theater.player import Player


@dataclass
class CustomAirdropTarget(MissionTarget):
    name: str
    position: Point
    troop_count: int = 8
    cargo_weight: int = 0
    requires_helicopter: bool = True
    _coalition: Any = field(default=None, repr=False)

    def is_friendly(self, to_player: Player) -> bool:
        return False

    @property
    def coalition(self) -> Coalition:
        return self._coalition

    def mission_types(self, for_player: Player) -> Iterator[FlightType]:
        from game.ato.flighttype import FlightType

        yield FlightType.AIR_ASSAULT
        yield FlightType.TRANSPORT
        yield FlightType.LOGISTIC


def create_custom_airdrop_target(
    name: str, position: Point, coalition: Optional[Coalition] = None
) -> CustomAirdropTarget:
    return CustomAirdropTarget(name=name, position=position, _coalition=coalition)
