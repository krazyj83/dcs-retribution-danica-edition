"""Batch 2 of the 29 Sep quality check: one set of stock thresholds, old saves
load without lazy-init shims, CSV import only edits BLUEFOR depots, one helper
for the mission data tables."""

from __future__ import annotations

import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from dcs import Mission

from game.logistics import LogisticsManager, WarehouseCategory, new_base_warehouse
from game.logistics.levels import estimate, level, level_status
from game.logistics.supply_status import classify
from game.missiongenerator.luadata import (
    DATA_TRIGGER_PREFIX,
    inject_data_table,
    to_lua,
)
from game.theater.player import Player
from qt_ui.windows.logistics.QLogisticsWindow import import_warehouse_csv

FUEL = WarehouseCategory.FUEL


def _cp(name: str, side: Player) -> Any:
    return SimpleNamespace(id=uuid4(), name=name, captured=side)


# --- levels --------------------------------------------------------------------


def test_one_set_of_thresholds() -> None:
    assert level(0, 1000) == 0.0
    assert level(2000, 1000) == 1.0  # clamped
    assert level(10, 0) == 0.0  # no capacity is empty, not a crash
    assert level_status(0.0) == "empty"
    assert level_status(0.1) == "critical"
    assert level_status(0.3) == "low"
    assert level_status(0.4) == "ok"
    assert estimate(0.0)[0] == "Exhausted"
    assert estimate(0.33)[0].startswith("Low")


def test_empty_weapon_types_warn() -> None:
    assert classify(1.0, 1.0, None, False, weapon_types=10, weapons_empty=2) == (
        "low",
        ["2 weapon type(s) empty"],
    )
    status, _ = classify(1.0, 1.0, None, False, weapon_types=4, weapons_empty=2)
    assert status == "critical"  # half the weapon types gone


def test_critical_ammunition() -> None:
    assert classify(0.5, 0.1, None, False) == ("critical", ["ammunition 10%"])


# --- old saves -----------------------------------------------------------------


def test_old_logistics_saves_get_new_fields() -> None:
    lm = LogisticsManager()
    state = dict(lm.__dict__)
    for key in ("_history", "_debrief_log", "_red_intel", "_red_grounded"):
        state.pop(key, None)
    old = LogisticsManager.__new__(LogisticsManager)
    old.__setstate__(state)
    assert old._history == {}
    assert old._debrief_log == []
    assert old._red_grounded == {}


def test_logistics_pickles() -> None:
    lm = LogisticsManager()
    lm.add_debrief_log(["hello"])
    copy = pickle.loads(pickle.dumps(lm))
    assert copy.pop_debrief_log() == ["hello"]


# --- CSV import ----------------------------------------------------------------


def test_csv_import_skips_enemy_depots(tmp_path: Path) -> None:
    lm = LogisticsManager()
    blue = new_base_warehouse(_cp("Kutaisi", Player.BLUE))
    red = new_base_warehouse(_cp("Sochi", Player.RED))
    lm.add_warehouse(blue)
    lm.add_warehouse(red)
    red_fuel = red.stock[FUEL].quantity
    path = tmp_path / "stock.csv"
    path.write_text("base,fuel\nKutaisi,123\nSochi,1\n", encoding="utf-8")

    imported, warnings = import_warehouse_csv(lm, str(path))

    assert imported == 1
    assert blue.stock[FUEL].quantity == 123
    assert red.stock[FUEL].quantity == red_fuel
    assert warnings == ["Unknown or enemy base 'Sochi' - skipped"]


# --- mission data tables -------------------------------------------------------


def test_to_lua() -> None:
    assert to_lua({"a": [1, 2.5, True, None]}) == '{["a"] = {1, 2.5, true, nil}}'
    assert to_lua('say "hi"\n') == '"say \\"hi\\"\\n"'
    assert to_lua(float("inf")) == "math.huge"
    assert to_lua(float("-inf")) == "-math.huge"
    assert to_lua(float("nan")) == "(0/0)"
    with pytest.raises(TypeError):
        to_lua(object())


def test_inject_data_table() -> None:
    mission = Mission()
    inject_data_table(mission, "dcsRetributionTest", {"x": 1}, "test")
    trigger = mission.triggerrules.triggers[-1]
    assert trigger.comment == f"{DATA_TRIGGER_PREFIX} test data"
    assert trigger.actions[0].dict()["text"] == 'dcsRetributionTest = {["x"] = 1}'
