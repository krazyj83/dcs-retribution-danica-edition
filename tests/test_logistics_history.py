"""Stock history per base and the map's base supply status."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.history import MAX_TURNS, history_for, record_turn
from game.logistics.supply_status import classify, supply_status
from game.server.app import app
from game.server.dependencies import GameContext
from game.theater.player import Player

FUEL, AMMO = WarehouseCategory.FUEL, WarehouseCategory.AMMUNITION


def _base(name: str, side: Player = Player.BLUE) -> Any:
    position: Any = SimpleNamespace(
        latlng=lambda: SimpleNamespace(lat=34.9, lng=33.6),
    )
    return SimpleNamespace(id=uuid4(), name=name, captured=side, position=position)


def _game(*bases: Any, unlimited: bool = False) -> Any:
    logistics = LogisticsManager()
    for b in bases:
        logistics.add_warehouse(Warehouse(cp_id=b.id, cp_name=b.name))
    return SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(logistics_unlimited_fuel=unlimited),
        theater=SimpleNamespace(controlpoints=list(bases)),
        turn=1,
    )


def test_one_point_per_turn_replaced_on_regeneration() -> None:
    base = _base("Larnaca")
    game = _game(base)
    wh = game.logistics.get_warehouse(base.id)

    record_turn(game.logistics, 1)
    wh.stock[FUEL].quantity = 300
    record_turn(game.logistics, 1)  # mission regenerated
    record_turn(game.logistics, 2)

    points = history_for(game.logistics, base.id)
    assert [p.turn for p in points] == [1, 2]
    assert points[0].fuel == 300


def test_history_is_capped() -> None:
    base = _base("Larnaca")
    game = _game(base)
    for turn in range(MAX_TURNS + 5):
        record_turn(game.logistics, turn)
    points = history_for(game.logistics, base.id)
    assert len(points) == MAX_TURNS and points[0].turn == 5


def test_on_turn_end_records_after_attrition(monkeypatch: Any) -> None:
    base = _base("Larnaca")
    game = _game(base)
    game.turn = 4
    monkeypatch.setattr(
        "game.logistics.transfer_flights.flight_for_transfer", lambda *a: None
    )

    game.logistics.on_turn_end(game)

    (point,) = history_for(game.logistics, base.id)
    assert point.turn == 4 and point.fuel == 495  # 500 less 1% attrition


def test_old_saves_without_history_still_record() -> None:
    base = _base("Larnaca")
    game = _game(base)
    del game.logistics._history
    record_turn(game.logistics, 1)
    assert len(history_for(game.logistics, base.id)) == 1


def test_classify() -> None:
    assert classify(0.5, 0.5, None, False) == ("ok", [])
    assert classify(0.5, 0.5, 2.0, False)[0] == "low"
    assert classify(0.3, 0.5, None, False) == ("low", ["fuel 30%"])
    assert classify(0.5, 0.2, None, False) == ("low", ["ammunition 20%"])
    assert classify(0.5, 0.5, 0.5, False) == (
        "critical",
        ["fuel for less than 1 turn"],
    )
    assert classify(0.0, 0.5, None, True) == ("critical", ["out of fuel"])
    # Unlimited fuel: only an empty tank counts.
    assert classify(0.3, 0.5, 0.2, True) == ("ok", [])


def test_supply_status_covers_friendly_bases_only() -> None:
    blue, red = _base("Larnaca"), _base("Kobuleti", Player.RED)
    game = _game(blue, red)
    game.logistics.get_warehouse(blue.id).stock[AMMO].quantity = 100

    (status,) = supply_status(game)

    assert status.cp is blue
    assert status.status == "low" and status.reasons == ["ammunition 10%"]


def test_supply_status_endpoint() -> None:
    blue = _base("Larnaca")
    game = _game(blue)
    old = getattr(GameContext, "_game_model", None)
    GameContext._game_model = SimpleNamespace(game=game)  # type: ignore[assignment]
    try:
        response = TestClient(app).get("/logistics/supply-status")
    finally:
        if old is not None:
            GameContext._game_model = old
    assert response.status_code == 200
    (row,) = response.json()
    assert row["name"] == "Larnaca" and row["status"] == "ok"
    assert row["fuel"] == 500 and row["position"] == {"lat": 34.9, "lng": 33.6}
