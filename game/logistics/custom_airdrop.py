from dataclasses import dataclass, field
from typing import TYPE_CHECKING

try:
    from game.theater.missiontarget import MissionTarget
except Exception:
    class MissionTarget:
        def __init__(self, name, position):
            self.name = name
            self.position = position

if TYPE_CHECKING:
    from game.coalition import Coalition

@dataclass
class CustomAirdropTarget(MissionTarget):
    name: str
    position: object
    troop_count: int = 8
    cargo_weight: int = 0
    requires_helicopter: bool = True
    _coalition: object = field(default=None, repr=False)

    def is_friendly(self, to_player) -> bool:
        return False

    @property
    def coalition(self) -> "Coalition":
        return self._coalition

    def mission_types(self, for_player=True):
        try:
            from game.ato.flighttype import FlightType
            return [
                FlightType.AIR_ASSAULT,
                FlightType.TRANSPORT,
                FlightType.LOGISTIC,
            ]
        except Exception:
            return []


def create_custom_airdrop_target(name, position, coalition=None):
    return CustomAirdropTarget(
        name=name,
        position=position,
        _coalition=coalition,
    )
