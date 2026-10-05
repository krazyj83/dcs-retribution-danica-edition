"""Convoy routes with waypoints between start and end."""

from __future__ import annotations

import pickle
from typing import Any
from uuid import uuid4

from dcs.mapping import LatLng, Point
from dcs.mission import Mission
from dcs.point import PointAction
from fastapi.testclient import TestClient

from game.server.app import app
from game.theater.convoyroute import ConvoyRouteTarget, PlayerConvoyRoute
from game.unitmap import UnitMap
from game.utils import meters
from tests.missiongenerator.test_playerconvoygenerator import (
    BRADLEY,
    ROUTE_END,
    ROUTE_START,
    TERRAIN,
    _game,
    _near_end,
    _near_start,
)
from tests.test_convoy_routes_per_turn import ROUTE, game  # noqa: F401 (fixture)

VIA = [{"lat": 42.20, "lng": 42.55}, {"lat": 42.23, "lng": 42.62}]


def test_waypoints_are_stored_and_returned(game: Any) -> None:  # noqa: F811
    client = TestClient(app)
    created = client.post("/convoy-routes/", json={**ROUTE, "via": VIA})
    assert created.status_code == 201
    assert created.json()["via"] == VIA
    route = next(iter(game.player_convoy_routes.values()))
    assert route.via == [(42.20, 42.55), (42.23, 42.62)]
    assert route.points[0] == (ROUTE["start_lat"], ROUTE["start_lng"])
    assert route.points[-1] == (ROUTE["end_lat"], ROUTE["end_lng"])
    assert len(route.points) == 4


def test_a_route_without_waypoints_still_works(game: Any) -> None:  # noqa: F811
    created = TestClient(app).post("/convoy-routes/", json=ROUTE)
    assert created.json()["via"] == []


def test_routes_saved_before_waypoints_load_without_any() -> None:
    route = PlayerConvoyRoute(uuid4(), "Old", 1.0, 2.0, 3.0, 4.0)
    state = dict(route.__dict__)
    del state["via"]
    old = PlayerConvoyRoute.__new__(PlayerConvoyRoute)
    old.__setstate__(state)
    assert old.via == [] and old.points == [(1.0, 2.0), (3.0, 4.0)]
    assert pickle.loads(pickle.dumps(old)).via == []


def test_the_convoy_drives_through_every_waypoint_in_order() -> None:
    route = PlayerConvoyRoute(
        uuid4(),
        "Winding road",
        ROUTE_START.lat,
        ROUTE_START.lng,
        ROUTE_END.lat,
        ROUTE_END.lng,
        via=[(42.20, 42.55), (42.23, 42.62)],
    )
    source = _near_start("Source", {BRADLEY: 2})
    mission = Mission(TERRAIN)
    from game.missiongenerator.playerconvoygenerator import PlayerConvoyGenerator

    PlayerConvoyGenerator(
        mission, _game([source, _near_end("Delivery", {})], [route]), UnitMap()
    ).generate()
    (group,) = mission.country("USA").vehicle_group
    points = group.points
    assert len(points) == 4  # start, 2 waypoints, end
    assert all(p.action == PointAction.OnRoad for p in points)
    for point, (lat, lng) in zip(points[1:3], route.via):
        expected = Point.from_latlng(LatLng(lat, lng), TERRAIN)
        assert abs(point.position.x - expected.x) < 1
        assert abs(point.position.y - expected.y) < 1


def _target(via: list[Point]) -> ConvoyRouteTarget:
    start, end = Point(0, 0, TERRAIN), Point(30_000, 0, TERRAIN)
    return ConvoyRouteTarget(
        name="MSR",
        position=Point(15_000, 0, TERRAIN),
        start=start,
        end=end,
        via=via,
    )


def test_route_length_runs_through_the_waypoints() -> None:
    assert _target([]).path_length.meters == 30_000
    # A detour 20 km north: 25 km out to it, 25 km back down.
    detour = _target([Point(15_000, 20_000, TERRAIN)])
    assert abs(detour.path_length.meters - 50_000) < 1
    assert detour.path_length > meters(30_000)


def test_escort_covers_and_times_the_whole_route() -> None:
    from types import SimpleNamespace

    from game.ato.flightplans.convoyescort import ConvoyEscortFlightPlan
    from game.theater.convoyroute import drive_time

    detour = _target([Point(15_000, 20_000, TERRAIN)])
    plan: Any = object.__new__(ConvoyEscortFlightPlan)
    plan.flight = SimpleNamespace(package=SimpleNamespace(target=detour))
    assert abs(plan.route_length.meters - 50_000) < 1
    _, slowest = drive_time(plan.route_length)
    assert slowest > drive_time(meters(30_000))[1]
