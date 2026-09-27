"""Convoy route API routes.

Routes are stored on the game (``Game.player_convoy_routes``), so they are
saved with the campaign, belong to that campaign only, and are removed at
the end of each turn (see ``Game.finish_turn``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from starlette.responses import Response

from game.server.dependencies import GameContext
from game.server.leaflet import LeafletPoint
from .models import ConvoyRouteJs, CreateConvoyRouteRequest

if TYPE_CHECKING:
    from game.theater.convoyroute import PlayerConvoyRoute

router: APIRouter = APIRouter(prefix="/convoy-routes")


def _routes() -> Optional[dict[UUID, PlayerConvoyRoute]]:
    """The current game's convoy routes, or None when no game is loaded."""
    game = GameContext.get()
    if game is None:
        return None
    if not hasattr(game, "player_convoy_routes"):
        game.player_convoy_routes = {}
    return game.player_convoy_routes


def _to_js(route: PlayerConvoyRoute) -> ConvoyRouteJs:
    return ConvoyRouteJs(
        id=route.id,
        name=route.name,
        start=LeafletPoint(lat=route.start_lat, lng=route.start_lng),
        end=LeafletPoint(lat=route.end_lat, lng=route.end_lng),
    )


def get_all() -> list[ConvoyRouteJs]:
    routes = _routes()
    if routes is None:
        return []
    return [_to_js(r) for r in routes.values()]


def clear_all() -> None:
    routes = _routes()
    if routes is not None:
        routes.clear()


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
    from game.theater.convoyroute import PlayerConvoyRoute

    routes = _routes()
    if routes is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No game loaded — cannot create convoy route.",
        )
    route = PlayerConvoyRoute(
        id=uuid4(),
        name=body.name.strip() or "Convoy Route",
        start_lat=body.start_lat,
        start_lng=body.start_lng,
        end_lat=body.end_lat,
        end_lng=body.end_lng,
    )
    routes[route.id] = route
    return _to_js(route)


@router.delete(
    "/{route_id}",
    operation_id="delete_convoy_route",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_convoy_route(route_id: UUID) -> None:
    routes = _routes()
    if routes is None or route_id not in routes:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"No convoy route {route_id}"
        )
    del routes[route_id]
