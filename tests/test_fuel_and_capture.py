"""Warehouse fuel used by sorties, the unlimited fuel setting, and what a base
keeps when it is captured."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from dcs.planes import F_16C_50, KC_135

from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.base_inventory import base_inventory
from game.logistics.capture import CAPTURE_SALVAGE_STOCK
from game.logistics.fuel import (
    fuel_per_aircraft,
    fuel_warning,
    turns_left,
    use_fuel_for_sorties,
)
from game.theater.player import Player

FUEL, AMMO = WarehouseCategory.FUEL, WarehouseCategory.AMMUNITION


def _cp(name: str, side: Player = Player.BLUE) -> Any:
    return SimpleNamespace(id=uuid4(), name=name, captured=side)


def _aircraft(dcs_type: Any) -> Any:
    return SimpleNamespace(dcs_unit_type=dcs_type)


def _flight(base: Any, count: int, dcs_type: Any = F_16C_50) -> Any:
    return SimpleNamespace(departure=base, count=count, unit_type=_aircraft(dcs_type))


def _game(flights: list[Any], unlimited: bool = False, *bases: Any) -> Any:
    logistics = LogisticsManager()
    for base in bases:
        logistics.add_warehouse(Warehouse(cp_id=base.id, cp_name=base.name))
    return SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(logistics_unlimited_fuel=unlimited),
        blue=SimpleNamespace(
            ato=SimpleNamespace(packages=[SimpleNamespace(flights=flights)])
        ),
        theater=SimpleNamespace(controlpoints=list(bases)),
        turn=1,
    )


def _fuel(game: Any, base: Any) -> float:
    return game.logistics.get_warehouse(base.id).stock[FUEL].quantity


def test_fuel_per_aircraft_follows_internal_fuel() -> None:
    assert fuel_per_aircraft(_aircraft(F_16C_50)) == pytest.approx(3249 / 200)
    assert fuel_per_aircraft(_aircraft(KC_135)) == 100  # capped


def test_sorties_use_their_base_fuel() -> None:
    base = _cp("Larnaca")
    game = _game([_flight(base, 4), _flight(base, 2)], False, base)

    log = use_fuel_for_sorties(game)

    used = 6 * 3249 / 200
    assert _fuel(game, base) == pytest.approx(500 - used)
    wh = game.logistics.get_warehouse(base.id)
    assert wh.fuel_used_last_mission == pytest.approx(used)
    assert turns_left(wh) == pytest.approx((500 - used) / used)
    assert "6 sortie(s)" in log[0] and "turns at this rate" in log[0]


def test_running_dry_is_reported_but_not_negative() -> None:
    base = _cp("Paphos")
    game = _game([_flight(base, 12, KC_135)], False, base)

    log = use_fuel_for_sorties(game)

    assert _fuel(game, base) == 0
    assert "OUT OF FUEL" in log[0]
    assert "out of fuel" in (fuel_warning(game, base) or "")


def test_unlimited_fuel_uses_nothing() -> None:
    base = _cp("Larnaca")
    game = _game([_flight(base, 4)], True, base)

    assert use_fuel_for_sorties(game) == []
    assert _fuel(game, base) == 500
    assert fuel_warning(game, base) is None


def test_unlimited_fuel_also_skips_fuel_attrition() -> None:
    base = _cp("Larnaca")
    game = _game([], True, base)

    game.logistics.on_turn_end(game)

    wh = game.logistics.get_warehouse(base.id)
    assert wh.stock[FUEL].quantity == 500
    assert wh.stock[AMMO].quantity == pytest.approx(495)  # 1% attrition


def test_base_lost_during_the_mission_uses_nothing() -> None:
    base = _cp("Lost", Player.RED)
    game = _game([_flight(base, 4)], False, base)
    assert use_fuel_for_sorties(game) == []


def _stocked(logistics: LogisticsManager, base: Any) -> None:
    from game.logistics import WeaponInventory

    wh = Warehouse(cp_id=base.id, cp_name=base.name)
    wh.stock[FUEL].quantity = 640
    logistics.add_warehouse(wh)
    inv = WeaponInventory(cp_id=base.id, cp_name=base.name)
    inv.add_item("{AIM120C}", "AIM-120C", "Air-to-Air", quantity=40)
    inv.add_item("{GBU12}", "GBU-12", "Bomb", quantity=16)
    logistics.set_weapon_inventory(inv)


def test_lost_base_keeps_fuel_and_loses_weapons() -> None:
    base = _cp("Larnaca")
    logistics = LogisticsManager()
    _stocked(logistics, base)

    logistics.on_base_captured(base, Player.RED)

    wh = logistics.get_warehouse(base.id)
    assert wh is not None  # the warehouse stays with the base
    assert wh.stock[FUEL].quantity == 640
    assert all(wh.stock[c].quantity == 0 for c in WarehouseCategory if c is not FUEL)
    inv = logistics.get_weapon_inventory(base.id)
    assert inv is not None
    assert all(item.quantity == 0 for item in inv.items.values())
    log = logistics.pop_debrief_log()
    assert "56 weapons lost" in log[0]
    assert "fuel kept (640)" in log[1]


def test_retaken_base_keeps_fuel_gets_salvage_and_no_weapons() -> None:
    base = _cp("Larnaca")
    logistics = LogisticsManager()
    _stocked(logistics, base)

    logistics.on_base_captured(base, Player.RED)
    logistics.on_base_captured(base, Player.BLUE)

    wh = logistics.get_warehouse(base.id)
    assert wh is not None
    assert wh.stock[FUEL].quantity == 640
    assert wh.stock[AMMO].quantity == CAPTURE_SALVAGE_STOCK
    inv = logistics.get_weapon_inventory(base.id)
    assert inv is not None
    assert sum(i.quantity for i in inv.items.values()) == 0


def test_captured_enemy_base_without_warehouse_gets_one() -> None:
    base = _cp("Kobuleti")
    logistics = LogisticsManager()

    logistics.on_base_captured(base, Player.BLUE)

    wh = logistics.get_warehouse(base.id)
    assert wh is not None
    assert wh.stock[FUEL].quantity == 500  # default tank farm
    assert wh.stock[AMMO].quantity == CAPTURE_SALVAGE_STOCK


def test_debrief_log_is_handed_out_once() -> None:
    logistics = LogisticsManager()
    logistics.add_debrief_log(["a"])
    assert logistics.pop_debrief_log() == ["a"]
    assert logistics.pop_debrief_log() == []


def test_base_inventory_reports_turns_left() -> None:
    base = _cp("Larnaca")
    game = _game([_flight(base, 4)], False, base)
    use_fuel_for_sorties(game)

    inv = base_inventory(game, base)

    assert inv.fuel_used_last_mission == pytest.approx(4 * 3249 / 200)
    assert inv.fuel_turns_left is not None and inv.fuel_turns_left > 1
    assert not inv.unlimited_fuel


def test_ships_use_no_warehouse_fuel() -> None:
    carrier = _cp("CVN-74")
    carrier.is_fleet = True
    game = _game([_flight(carrier, 4)], False, carrier)

    assert use_fuel_for_sorties(game) == []
    assert _fuel(game, carrier) == 500
    assert fuel_warning(game, carrier) is None


def test_blue_bases_get_bigger_fuel_tanks() -> None:
    from game.logistics import BLUE_FUEL_CAPACITY, new_base_warehouse
    from game.logistics.history import ensure_friendly_warehouses

    base, old = _cp("Larnaca"), _cp("Paphos")
    game = _game([], False, old)  # Paphos: a warehouse from an older save
    game.theater.controlpoints = [base, old]

    ensure_friendly_warehouses(game)

    new_wh = game.logistics.get_warehouse(base.id)
    assert new_wh.stock[FUEL].quantity == new_wh.stock[FUEL].capacity == 2000
    old_wh = game.logistics.get_warehouse(old.id)
    assert old_wh.stock[FUEL].capacity == BLUE_FUEL_CAPACITY
    assert old_wh.stock[FUEL].quantity == 500  # bigger tank, same fuel
    assert new_base_warehouse(base).stock[AMMO].quantity == 500
