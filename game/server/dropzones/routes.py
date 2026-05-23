from __future__ import annotations
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, status
from starlette.responses import Response
from game.server.leaflet import LeafletPoint
from .models import CreateDropZoneRequest, DropZoneJs

router: APIRouter = APIRouter(prefix="/drop-zones")

# ---------------------------------------------------------------------------
# In-memory store  (lives for the lifetime of the server process)
# ---------------------------------------------------------------------------
_store: dict[UUID, DropZoneJs] = {}


def get_all() -> list[DropZoneJs]:
    return list(_store.values())


def get_by_id(dz_id: UUID) -> DropZoneJs | None:
    return _store.get(dz_id)


def clear_all() -> None:
    """Reset when a new game is loaded."""
    _store.clear()


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
    dz = DropZoneJs(
        id=uuid4(),
        name=body.name.strip() or "Drop Zone",
        position=LeafletPoint(lat=body.lat, lng=body.lng),
    )
    _store[dz.id] = dz
    return dz


@router.delete(
    "/{dz_id}",
    operation_id="delete_drop_zone",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_drop_zone(dz_id: UUID) -> None:
    if dz_id not in _store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No drop zone {dz_id}")
    del _store[dz_id]
