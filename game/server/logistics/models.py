from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel

from game.server.leaflet import LeafletPoint

if TYPE_CHECKING:
    from game import Game
    from game.logistics.supply_status import BaseSupply


class BaseSupplyJs(BaseModel):
    """Fuel and ammunition of one friendly base, for the map's supply layer."""

    id: UUID
    name: str
    position: LeafletPoint
    fuel: float
    fuel_capacity: float
    ammunition: float
    ammunition_capacity: float
    supplies: float
    supplies_capacity: float
    fuel_turns_left: Optional[float]
    unlimited_fuel: bool
    #: "ok", "low" or "critical" (see game/logistics/supply_status.py).
    status: str
    reasons: list[str]
    #: "blue", or "red" for an enemy base known from recon (amounts in %).
    side: str = "blue"
    intel_age: Optional[int] = None

    class Config:
        title = "BaseSupply"

    @staticmethod
    def from_status(s: BaseSupply) -> BaseSupplyJs:
        return BaseSupplyJs(
            id=s.cp.id,
            name=s.cp.name,
            position=s.cp.position.latlng(),
            fuel=s.fuel,
            fuel_capacity=s.fuel_capacity,
            ammunition=s.ammunition,
            ammunition_capacity=s.ammunition_capacity,
            supplies=s.supplies,
            supplies_capacity=s.supplies_capacity,
            fuel_turns_left=s.fuel_turns_left,
            unlimited_fuel=s.unlimited_fuel,
            status=s.status,
            reasons=s.reasons,
            side=s.side,
            intel_age=s.intel_age,
        )

    @staticmethod
    def all_in_game(game: Game) -> list[BaseSupplyJs]:
        from game.logistics.supply_status import supply_status

        try:
            return [BaseSupplyJs.from_status(s) for s in supply_status(game)]
        except Exception:  # never break loading the map over this layer
            import logging

            logging.exception("Could not build the base supply status")
            return []
