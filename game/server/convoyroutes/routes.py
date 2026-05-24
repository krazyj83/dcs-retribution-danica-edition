from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from starlette.responses import Response

from game.server.leaflet import LeafletPoint
from .models import ConvoyRouteJs, CreateConvoyRouteRequest

router: APIRouter = APIRouter(prefix="/convoy-routes")

# ---------------------------------------------------------------------------
# In-memory store — same pattern as drop zones.
# Keyed by UUID, lives for the lifetime of the server process.
# ---------------------------------------------------------------------------
_store: dict[UUID, ConvoyRouteJs] = {}


def get_all() -> list[ConvoyRouteJs]:
    return list(_store.values())


def clear_all() -> None:
    """Reset when a new game is loaded."""
    _store.clear()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/",
    operation_id="list_convoy_routes",
    response_model=list[ConvoyRouteJs],
)
def list_convoy_routes() -> list[ConvoyRouteJs]:
    return get_all()


@router.post(
    "/",
    operation_id="create_convoy_route",
    response_model=ConvoyRouteJs,
    status_code=status.HTTP_201_CREATED,
)
def create_convoy_route(body: CreateConvoyRouteRequest) -> ConvoyRouteJs:
    route = ConvoyRouteJs(
        id=uuid4(),
        name=body.name.strip() or "Convoy Route",
        start=LeafletPoint(lat=body.start_lat, lng=body.start_lng),
        end=LeafletPoint(lat=body.end_lat, lng=body.end_lng),
    )
    _store[route.id] = route
    return route


@router.delete(
    "/{route_id}",
    operation_id="delete_convoy_route",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_convoy_route(route_id: UUID) -> None:
    if route_id not in _store:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No convoy route {route_id}"
        )
    del _store[route_id]
