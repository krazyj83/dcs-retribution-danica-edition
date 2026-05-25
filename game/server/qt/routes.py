from uuid import UUID
from dcs import Point
from dcs.mapping import LatLng
from fastapi import APIRouter, Depends, HTTPException, status
from game import Game
from game.logistics.custom_airdrop import CustomAirdropTarget
from game.server.dropzones.routes import get_by_id as get_drop_zone
from game.server.convoyroutes.routes import get_all as get_all_convoy_routes
from game.theater.convoyroute import ConvoyRouteTarget
from ..dependencies import GameContext, QtCallbacks, QtContext
from pydantic import BaseModel

router: APIRouter = APIRouter(prefix="/qt")


@router.post(
    "/create-package/front-line/{front_line_id}",
    operation_id="open_new_front_line_package_dialog",
    status_code=status.HTTP_200_OK,
)
def new_front_line_package(
    front_line_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    qt.create_new_package(game.db.front_lines.get(front_line_id))


@router.post(
    "/create-package/tgo/{tgo_id}",
    operation_id="open_new_tgo_package_dialog",
    status_code=status.HTTP_200_OK,
)
def new_tgo_package(
    tgo_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    qt.create_new_package(game.db.tgos.get(tgo_id))


@router.post(
    "/info/tgo/{tgo_id}",
    operation_id="open_tgo_info_dialog",
    status_code=status.HTTP_200_OK,
)
def show_tgo_info(
    tgo_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    qt.show_tgo_info(game.db.tgos.get(tgo_id))


@router.post(
    "/create-package/control-point/{cp_id}",
    operation_id="open_new_control_point_package_dialog",
    status_code=status.HTTP_200_OK,
)
def new_cp_package(
    cp_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    cp = game.theater.find_control_point_by_id(cp_id)
    if cp is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Game has no control point with ID {cp_id}",
        )
    qt.create_new_package(cp)


@router.post(
    "/info/control-point/{cp_id}",
    operation_id="open_control_point_info_dialog",
    status_code=status.HTTP_200_OK,
)
def show_control_point_info(
    cp_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    cp = game.theater.find_control_point_by_id(cp_id)
    if cp is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Game has no control point with ID {cp_id}",
        )
    qt.show_control_point_info(cp)


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
    """Open the Retribution New Package dialog targeting a player-placed drop zone."""
    dz = get_drop_zone(dz_id)
    if dz is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No drop zone with id {dz_id}",
        )
    # dz is a raw logistics.DropZone with .lat/.lon attributes
    try:
        lat = dz.lat
        lon = dz.lon
    except AttributeError:
        lat = dz.position.lat
        lon = dz.position.lng
    position = Point.from_latlng(
        LatLng(lat, lon),
        game.theater.terrain,
    )
    target = CustomAirdropTarget(name=dz.name, position=position, _coalition=game.blue)
    qt.create_new_package(target)


@router.post(
    "/create-package/convoy-route/{route_id}",
    operation_id="open_new_convoy_route_package_dialog",
    status_code=status.HTTP_200_OK,
)
def new_convoy_route_package(
    route_id: UUID,
    game: Game = Depends(GameContext.require),
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    """Open the New Package dialog pre-set for escorting a player-drawn convoy route."""
    all_routes = get_all_convoy_routes()
    route = next((r for r in all_routes if r.id == route_id), None)
    if route is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No convoy route with id {route_id}",
        )
    terrain = game.theater.terrain
    start_point = Point.from_latlng(
        LatLng(route.start.lat, route.start.lng), terrain
    )
    end_point = Point.from_latlng(
        LatLng(route.end.lat, route.end.lng), terrain
    )
    mid_point = Point(
        (start_point.x + end_point.x) / 2,
        (start_point.y + end_point.y) / 2,
        terrain,
    )
    target = ConvoyRouteTarget(
        name=route.name,
        position=mid_point,
        start=start_point,
        end=end_point,
        _coalition=game.blue,
    )
    qt.create_new_package(target)


class OpenDropZoneDialogRequest(BaseModel):
    lat: float
    lng: float


@router.post(
    "/open-drop-zone-dialog",
    operation_id="open_drop_zone_dialog",
    status_code=status.HTTP_200_OK,
)
def open_drop_zone_dialog(
    body: OpenDropZoneDialogRequest,
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    """Open the logistics Drop Zone dialog pre-filled with map coordinates."""
    qt.open_drop_zone_dialog(body.lat, body.lng)
