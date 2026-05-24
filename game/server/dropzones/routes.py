"""
game/server/dropzones/routes.py

Drop zone API routes. Reads and writes directly from/to
game.logistics.LogisticsManager so the map and the Logistics window
always share the same data.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import Response

from game.server.dependencies import GameContext
from game.server.leaflet import LeafletPoint
from .models import CreateDropZoneRequest, DropZoneJs

router: APIRouter = APIRouter(prefix="/drop-zones")


def _get_logistics():
    """Return the LogisticsManager from the current game, or None."""
    game = GameContext.get()
    if game is None:
        return None
    return getattr(game, "logistics", None)


def _to_js(dz) -> DropZoneJs:
    """Convert a logistics.DropZone to the API model."""
    return DropZoneJs(
        id=UUID(dz.dz_id),
        name=dz.name,
        position=LeafletPoint(lat=dz.lat, lng=dz.lon),
    )


def get_all() -> list[DropZoneJs]:
    logistics = _get_logistics()
    if logistics is None:
        return []
    return [_to_js(dz) for dz in logistics._drop_zones.values()]


def get_by_id(dz_id: UUID):
    """Return the raw DropZone dataclass by id, or None."""
    logistics = _get_logistics()
    if logistics is None:
        return None
    return logistics._drop_zones.get(str(dz_id))


def clear_all() -> None:
    """Reset when a new game is loaded."""
    logistics = _get_logistics()
    if logistics is not None:
        logistics._drop_zones.clear()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", operation_id="list_drop_zones", response_model=list[DropZoneJs])
def list_drop_zones() -> list[DropZoneJs]:
    return get_all()


@router.post(
    "/",
    operation_id="create_drop_zone",
    response_model=DropZoneJs,
    status_code=status.HTTP_201_CREATED,
)
def create_drop_zone(body: CreateDropZoneRequest) -> DropZoneJs:
    from game.logistics import DropZone, DropZoneType

    logistics = _get_logistics()
    if logistics is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No game loaded — cannot create drop zone.",
        )

    dz_id = str(uuid4())

    # Find the nearest blue control point for the cp_id field
    game = GameContext.get()
    cp_id = 0
    cp_name = "Map point"
    coalition = "blue"
    if game is not None:
        try:
            from dcs.mapping import LatLng
            from dcs.unit import Point
            nearest = None
            nearest_dist = float("inf")
            for cp in game.theater.controlpoints:
                try:
                    ll = cp.position.latlng()
                    dist = ((ll.lat - body.lat) ** 2 + (ll.lng - body.lng) ** 2) ** 0.5
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest = cp
                except Exception:
                    pass
            if nearest is not None:
                cp_id = nearest.id
                cp_name = nearest.name
                try:
                    if nearest.captured.is_blue:
                        coalition = "blue"
                    elif nearest.captured.is_red:
                        coalition = "red"
                    else:
                        coalition = "neutral"
                except Exception:
                    pass
        except Exception:
            pass

    dz = DropZone(
        name=body.name.strip() or "Drop Zone",
        dz_type=DropZoneType.CARGO,
        lat=body.lat,
        lon=body.lng,
        cp_id=cp_id,
        cp_name=cp_name,
        coalition=coalition,
        dz_id=dz_id,
    )
    logistics.add_drop_zone(dz)
    return _to_js(dz)


@router.delete(
    "/{dz_id}",
    operation_id="delete_drop_zone",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_drop_zone(dz_id: UUID) -> None:
    logistics = _get_logistics()
    if logistics is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No game loaded.",
        )
    key = str(dz_id)
    if key not in logistics._drop_zones:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No drop zone {dz_id}",
        )
    logistics.remove_drop_zone(key)