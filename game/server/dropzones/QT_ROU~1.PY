# ── ADD THIS BLOCK to game/server/qt/routes.py ──────────────────────────────
# Place it after the existing "create-package/control-point" route.
#
# What it does:
#   1. Looks up the drop zone by ID from the in-memory store
#   2. Converts the lat/lng to a DCS theater Point
#   3. Wraps it in a CustomAirdropTarget  (already supports AIR_ASSAULT /
#      TRANSPORT / LOGISTIC mission types)
#   4. Calls qt.create_new_package() — opens the standard Retribution
#      "New Package" dialog exactly as if the player right-clicked a TGO
# ----------------------------------------------------------------------------

from uuid import UUID
from dcs import Point
from dcs.mapping import LatLng
from fastapi import APIRouter, Depends, HTTPException, status
from game import Game
from game.logistics.custom_airdrop import CustomAirdropTarget
from game.server.dropzones.routes import get_by_id as get_drop_zone
from ..dependencies import GameContext, QtCallbacks, QtContext

# (router is already defined in qt/routes.py — don't redeclare it)

@router.post(
    "/create-package/drop-zone/{dz_id}",
    operation_id="open_new_drop_zone_package_dialog",
    status_code=status.HTTP_200_OK,
)
def new_drop_zone_package(
    dz_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    dz = get_drop_zone(dz_id)
    if dz is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No drop zone with id {dz_id}",
        )
    position = Point.from_latlng(
        LatLng(dz.position.lat, dz.position.lng),
        game.theater.terrain,
    )
    target = CustomAirdropTarget(name=dz.name, position=position)
    qt.create_new_package(target)
