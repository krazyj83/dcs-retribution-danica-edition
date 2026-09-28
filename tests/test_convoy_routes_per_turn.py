"""Player-drawn convoy routes are saved with the game; one-off routes last one
turn, standing routes stay until removed."""

from __future__ import annotations

import pickle
from types import SimpleNamespace
from typing import Any, Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from game.game import Game
from game.server.app import app
from game.server.dependencies import GameContext
from game.theater.convoyroute import PlayerConvoyRoute

ROUTE = {
    "name": "MSR Tampa",
    "start_lat": 42.1,
    "start_lng": 42.4,
    "end_lat": 42.2,
    "end_lng": 42.7,
}


@pytest.fixture
def game() -> Iterator[Any]:
    fake = SimpleNamespace(player_convoy_routes={})
    old = getattr(GameContext, "_game_model", None)
    GameContext._game_model = SimpleNamespace(game=fake)  # type: ignore[assignment]
    yield fake
    if old is not None:
        GameContext._game_model = old


def test_created_route_is_stored_on_the_game(game: Any) -> None:
    client = TestClient(app)

    created = client.post("/convoy-routes/", json=ROUTE)

    assert created.status_code == 201
    assert len(game.player_convoy_routes) == 1
    route = next(iter(game.player_convoy_routes.values()))
    assert isinstance(route, PlayerConvoyRoute)
    assert str(route.id) == created.json()["id"]
    assert client.get("/convoy-routes/").json() == [created.json()]


def test_deleted_route_is_removed_from_the_game(game: Any) -> None:
    client = TestClient(app)
    route_id = client.post("/convoy-routes/", json=ROUTE).json()["id"]

    assert client.delete(f"/convoy-routes/{route_id}").status_code == 204
    assert game.player_convoy_routes == {}
    assert client.delete(f"/convoy-routes/{route_id}").status_code == 404


def test_no_game_loaded_refuses_to_create() -> None:
    old = getattr(GameContext, "_game_model", None)
    GameContext._game_model = SimpleNamespace(game=None)  # type: ignore[assignment]
    try:
        assert TestClient(app).post("/convoy-routes/", json=ROUTE).status_code == 503
    finally:
        if old is not None:
            GameContext._game_model = old


def _route() -> PlayerConvoyRoute:
    return PlayerConvoyRoute(
        id=uuid4(),
        name="R",
        start_lat=1.0,
        start_lng=2.0,
        end_lat=3.0,
        end_lng=4.0,
    )


def _bare_game() -> Any:
    """A Game object with only what finish_turn's first lines need."""
    game: Any = Game.__new__(Game)
    game.turn = 3
    game.informations = []
    game.player_convoy_routes = {}
    return game


class _StopAfterRouteCleanup(Exception):
    pass


def test_routes_are_removed_at_end_of_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    game = _bare_game()
    route = _route()
    game.player_convoy_routes[route.id] = route

    # Stop finish_turn right after the route cleanup; the rest needs a full game.
    def stop(*args: Any, **kwargs: Any) -> None:
        raise _StopAfterRouteCleanup

    monkeypatch.setattr(
        "game.game.RedforAdaptivePlanner", lambda *a, **k: SimpleNamespace(observe=stop)
    )
    game.bluefor_mission_history = object()

    with pytest.raises(_StopAfterRouteCleanup):
        game.finish_turn(events=None)

    assert game.player_convoy_routes == {}
    assert game.turn == 4


def test_old_saves_get_an_empty_route_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Game, "on_load", lambda self, *a, **k: None)
    game: Any = Game.__new__(Game)
    game.__setstate__({"laser_code_registry": object()})
    assert game.player_convoy_routes == {}
    # And a saved route survives a save/load round trip.
    route = _route()
    assert pickle.loads(pickle.dumps(route)) == route


def test_standing_routes_stay_one_off_routes_go() -> None:
    game = _bare_game()
    one_off, standing = _route(), _route()
    standing.repeat = True
    game.player_convoy_routes = {one_off.id: one_off, standing.id: standing}

    game.end_turn_convoy_routes()

    assert list(game.player_convoy_routes) == [standing.id]


def test_route_can_be_made_standing_and_back(game: Any) -> None:
    client = TestClient(app)
    created = client.post("/convoy-routes/", json={**ROUTE, "repeat": True}).json()
    assert created["repeat"] is True
    route_id = created["id"]

    updated = client.patch(f"/convoy-routes/{route_id}", json={"repeat": False})

    assert updated.status_code == 200 and updated.json()["repeat"] is False
    assert next(iter(game.player_convoy_routes.values())).repeat is False
    missing = client.patch(f"/convoy-routes/{uuid4()}", json={"repeat": True})
    assert missing.status_code == 404


def test_routes_saved_before_standing_routes_load_as_one_off() -> None:
    route = _route()
    state = dict(route.__dict__)
    del state["repeat"]
    old: Any = PlayerConvoyRoute.__new__(PlayerConvoyRoute)
    old.__setstate__(state)
    assert old.repeat is False and old.name == "R"
