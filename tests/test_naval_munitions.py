"""Naval munitions crates: mission data and ammunition charged to bases."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.naval_munitions import (
    AMMO_PER_CRATE,
    CRATE_KG,
    script_data,
    settle,
)
from game.theater.player import Player


def _game(ammo: float = 175.0) -> Any:
    cp = SimpleNamespace(
        id=uuid4(),
        name="Hatzor",
        captured=Player.BLUE,
        is_fleet=False,
        dcs_airport=object(),
        position=SimpleNamespace(x=1000.0, y=2000.0),
    )
    enemy = SimpleNamespace(
        id=uuid4(),
        name="H-3",
        captured=Player.RED,
        is_fleet=False,
        dcs_airport=object(),
        position=SimpleNamespace(x=0.0, y=0.0),
    )
    logistics = LogisticsManager()
    wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
    wh.stock[WarehouseCategory.AMMUNITION].quantity = ammo
    logistics.add_warehouse(wh)
    game = SimpleNamespace(
        logistics=logistics, theater=SimpleNamespace(controlpoints=[cp, enemy])
    )
    return game, cp, wh


def test_mission_data_lists_friendly_bases_and_their_crates() -> None:
    game, cp, _ = _game(ammo=175.0)

    data = script_data(game)

    assert data["crateKg"] == CRATE_KG
    assert [b["name"] for b in data["bases"]] == ["Hatzor"]
    base = data["bases"][0]
    assert base["id"] == str(cp.id)
    assert base["crates"] == int(175.0 // AMMO_PER_CRATE)
    assert (base["x"], base["z"]) == (1000.0, 2000.0)


def test_loaded_crates_are_charged_to_the_base() -> None:
    game, cp, wh = _game(ammo=500.0)

    log = settle(
        game, [{"base": str(cp.id), "name": "Hatzor", "loaded": 3, "delivered": 2}]
    )

    assert wh.stock[WarehouseCategory.AMMUNITION].quantity == 500.0 - 3 * AMMO_PER_CRATE
    assert "3 crate(s) taken from Hatzor" in log[0]
    assert "2 delivered to ships" in log[0]
    assert "1 not delivered" in log[0]


def test_returned_or_unreadable_reports_cost_nothing() -> None:
    game, cp, wh = _game(ammo=500.0)

    log = settle(
        game,
        [
            {"base": str(cp.id), "name": "Hatzor", "loaded": 0, "delivered": 0},
            {"base": "not-a-uuid", "loaded": 2},
        ],
    )

    assert wh.stock[WarehouseCategory.AMMUNITION].quantity == 500.0
    assert log == []


def test_base_without_a_warehouse_gets_the_default_one() -> None:
    game, cp, _ = _game()
    game.logistics._warehouses.clear()

    data = script_data(game)

    assert data["bases"][0]["crates"] > 0
    assert game.logistics.get_warehouse(cp.id) is not None
