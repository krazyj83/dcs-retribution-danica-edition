"""Base supply status for the map's "Base supply" layer."""

from __future__ import annotations

from fastapi import APIRouter

from game.server.dependencies import GameContext
from .models import BaseSupplyJs

router: APIRouter = APIRouter(prefix="/logistics")


@router.get(
    "/supply-status",
    operation_id="list_supply_status",
    response_model=list[BaseSupplyJs],
)
def list_supply_status() -> list[BaseSupplyJs]:
    game = GameContext.get()
    if game is None:
        return []
    return BaseSupplyJs.all_in_game(game)
