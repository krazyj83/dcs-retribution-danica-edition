"""The base window's Base Inventory tab: summary data and a Qt smoke test."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from game.logistics import (
    LogisticsManager,
    LogisticsTransfer,
    TransferStatus,
    WarehouseCategory,
    WeaponInventory,
)
from game.logistics.base_inventory import base_inventory


def _cp(name: str) -> Any:
    return SimpleNamespace(id=uuid4(), name=name)


def _game() -> tuple[Any, Any, Any]:
    home, other = _cp("Larnaca"), _cp("Paphos")
    logistics = LogisticsManager()
    game = SimpleNamespace(
        logistics=logistics,
        theater=SimpleNamespace(controlpoints=[home, other]),
    )
    return game, home, other


def _weapons(cp: Any) -> WeaponInventory:
    inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)
    inv.add_item("{AIM120C}", "AIM-120C", "Air-to-Air", quantity=100)
    inv.add_item("{AIM9X}", "AIM-9X", "Air-to-Air", quantity=0)
    inv.add_item("{GBU12}", "GBU-12", "Bomb", quantity=6)  # below 10: low
    inv.add_item("m1a2", "M1A2 Abrams ($25M)", "Armour", quantity=3)
    return inv


def test_new_base_gets_the_default_warehouse() -> None:
    game, home, _ = _game()

    inv = base_inventory(game, home)

    assert [r.category for r in inv.stock] == list(WarehouseCategory)
    assert all(r.quantity == 500 and r.capacity == 1000 for r in inv.stock)
    assert game.logistics.get_warehouse(home.id) is not None
    assert inv.weapons is None  # never synced


def test_stock_levels_and_resupply_flag() -> None:
    game, home, _ = _game()
    base_inventory(game, home)
    wh = game.logistics.get_warehouse(home.id)
    wh.stock[WarehouseCategory.FUEL].quantity = 300  # 30%: needs resupply
    wh.stock[WarehouseCategory.AMMUNITION].quantity = 175

    inv = base_inventory(game, home)
    fuel = next(r for r in inv.stock if r.category is WarehouseCategory.FUEL)

    assert fuel.level == pytest.approx(0.3)
    assert fuel.needs_resupply
    assert inv.naval_crates == 3  # 175 // 50


def test_weapons_are_grouped_and_ground_units_left_out() -> None:
    game, home, _ = _game()
    game.logistics.set_weapon_inventory(_weapons(home))

    inv = base_inventory(game, home)

    assert inv.weapons is not None
    assert list(inv.weapons) == ["Air-to-Air", "Bomb"]
    assert [r.name for r in inv.weapons["Air-to-Air"]] == ["AIM-120C", "AIM-9X"]
    assert inv.weapon_totals == (3, 1, 1)  # 3 types, AIM-9X empty, GBU-12 low


def test_same_weapon_on_different_racks_is_one_row() -> None:
    game, home, _ = _game()
    inv = WeaponInventory(cp_id=home.id, cp_name=home.name)
    inv.add_item("{AIM54_RAIL_A}", "AIM-54A-Mk47", "Air-to-Air", quantity=5)
    inv.add_item("{AIM54_RAIL_B}", "AIM-54A-Mk47", "Air-to-Air", quantity=20)
    game.logistics.set_weapon_inventory(inv)

    rows = base_inventory(game, home).weapons["Air-to-Air"]  # type: ignore[index]

    assert len(rows) == 1
    assert (rows[0].quantity, rows[0].capacity, rows[0].variants) == (25, 500, 2)
    assert not rows[0].low


def test_supply_flights_in_and_out() -> None:
    game, home, other = _game()

    def transfer(src: Any, dst: Any, status: TransferStatus) -> None:
        t = LogisticsTransfer(
            transfer_id=str(uuid4()),
            source_cp_id=src.id,
            dest_cp_id=dst.id,
            dz_id="",
            category=WarehouseCategory.FUEL,
            quantity=200,
            aircraft_type="C-130J-30",
            turn_planned=1,
            status=status,
        )
        game.logistics._transfers[t.transfer_id] = t

    transfer(other, home, TransferStatus.IN_FLIGHT)
    transfer(home, other, TransferStatus.PLANNED)
    transfer(other, home, TransferStatus.DELIVERED)  # done: not shown

    inv = base_inventory(game, home)

    assert inv.incoming == ["200 fuel from Paphos (in flight)"]
    assert inv.outgoing == ["200 fuel to Paphos (planned)"]


def test_tab_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    from qt_ui.windows.basemenu.inventory.QBaseInventory import QBaseInventory

    game, home, _ = _game()
    model: Any = SimpleNamespace(game=game)
    tab = QBaseInventory(home, model)

    # Not synced yet: the sync button is offered and fills the stores.
    assert "not been synced" in tab.weapon_summary.text()
    monkeypatch.setattr(
        game.logistics,
        "sync_weapon_inventories",
        lambda g: game.logistics.set_weapon_inventory(_weapons(home)),
        raising=False,
    )
    tab._on_sync()
    assert tab.tree.topLevelItemCount() == 2

    tab.search.setText("aim-9")
    assert tab.tree.topLevelItemCount() == 1
    assert tab.tree.topLevelItem(0).child(0).text(0) == "AIM-9X"

    tab.search.setText("")
    tab.only_low.setChecked(True)
    shown = [
        tab.tree.topLevelItem(i).child(j).text(0)
        for i in range(tab.tree.topLevelItemCount())
        for j in range(tab.tree.topLevelItem(i).childCount())
    ]
    assert sorted(shown) == ["AIM-9X", "GBU-12"]
    assert app is not None
