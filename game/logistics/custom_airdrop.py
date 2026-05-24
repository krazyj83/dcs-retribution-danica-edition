from dataclasses import dataclass
try:
    from game.theater.missiontarget import MissionTarget
except Exception:
    class MissionTarget:
        def __init__(self, name, position):
            self.name = name
            self.position = position

@dataclass
class CustomAirdropTarget(MissionTarget):
    name: str
    position: object
    troop_count: int = 8
    cargo_weight: int = 0
    requires_helicopter: bool = True

    def is_friendly(self, to_player) -> bool:
        # Drop zones are always placed by the player — always friendly territory.
        return True

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


def create_custom_airdrop_target(name, position, coalition="blue"):
    return CustomAirdropTarget(
        name=name,
        position=position,
    )
