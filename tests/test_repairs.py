"""Repairs cost warehouse supplies and ammunition (game/logistics/repairs.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from game.data.units import UnitClass
from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.repairs import (
    charge_repair,
    redfor_repair_air_defences,
    repair_cost,
    repair_shortfall,
)
from game.theater.player import Player

SUPPLIES, AMMO = WarehouseCategory.SUPPLIES, WarehouseCategory.AMMUNITION


def _unit(tgo: Any, unit_class: UnitClass, price: int, alive: bool = False) -> Any:
    unit: Any = SimpleNamespace(
        ground_object=tgo,
        unit_type=SimpleNamespace(price=price, unit_class=unit_class),
        alive=alive,
        repairable=True,
        type=SimpleNamespace(id=unit_class.value),
        position=None,
    )
    unit.revive = lambda events: setattr(unit, "alive", True)
    tgo.units.append(unit)
    return unit


def _site(cp: Any, category: str = "aa") -> Any:
    return SimpleNamespace(
        name="SA-11 site", category=category, control_point=cp, units=[]
    )


def _game(*cps: Any, sites: list[Any], red_repairs: bool = True) -> Any:
    logistics = LogisticsManager()
    for cp in cps:
        logistics.add_warehouse(Warehouse(cp_id=cp.id, cp_name=cp.name))
    return SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(
            redfor_logistics=True, redfor_repairs_air_defences=red_repairs
        ),
        theater=SimpleNamespace(ground_objects=sites, terrain=None),
        get_destroyed_units=lambda: [],
    )


def _cp(side: Player) -> Any:
    return SimpleNamespace(id=uuid4(), name="Base", captured=side, is_fleet=False)


def test_repair_cost() -> None:
    site = _site(_cp(Player.BLUE))
    assert repair_cost(_unit(site, UnitClass.LAUNCHER, 15)) == (25, 20)
    assert repair_cost(_unit(site, UnitClass.SEARCH_RADAR, 30)) == (40, 0)


def test_blue_repair_is_refused_without_stock_and_charged_with_it() -> None:
    cp = _cp(Player.BLUE)
    site = _site(cp)
    launcher = _unit(site, UnitClass.LAUNCHER, 15)
    game = _game(cp, sites=[site])
    wh = game.logistics.get_warehouse(cp.id)
    wh.stock[AMMO].quantity = 10

    assert repair_shortfall(game, launcher) == "Not enough ammunition (10 of 20)"

    wh.stock[AMMO].quantity = 100
    assert repair_shortfall(game, launcher) is None
    charge_repair(game, launcher)
    assert wh.stock[SUPPLIES].quantity == 475 and wh.stock[AMMO].quantity == 80


def test_red_repairs_one_unit_per_damaged_site_radars_first() -> None:
    cp = _cp(Player.RED)
    site = _site(cp)
    _unit(site, UnitClass.LAUNCHER, 15, alive=True)
    launcher = _unit(site, UnitClass.LAUNCHER, 15)
    radar = _unit(site, UnitClass.SEARCH_TRACK_RADAR, 30)
    game = _game(cp, sites=[site])

    log = redfor_repair_air_defences(game, events=object())

    assert radar.alive and not launcher.alive
    assert len(log) == 1
    assert game.logistics.get_warehouse(cp.id).stock[SUPPLIES].quantity == 460


def test_destroyed_sites_and_blue_sites_are_not_repaired() -> None:
    red, blue = _cp(Player.RED), _cp(Player.BLUE)
    dead_site = _site(red)
    dead = _unit(dead_site, UnitClass.LAUNCHER, 15)
    blue_site = _site(blue)
    _unit(blue_site, UnitClass.LAUNCHER, 15, alive=True)
    blue_dead = _unit(blue_site, UnitClass.LAUNCHER, 15)
    game = _game(red, blue, sites=[dead_site, blue_site])

    assert redfor_repair_air_defences(game, events=object()) == []
    assert not dead.alive and not blue_dead.alive


def test_red_repairs_stop_without_stock_or_setting() -> None:
    cp = _cp(Player.RED)
    site = _site(cp)
    _unit(site, UnitClass.LAUNCHER, 15, alive=True)
    launcher = _unit(site, UnitClass.LAUNCHER, 15)
    game = _game(cp, sites=[site], red_repairs=False)
    assert redfor_repair_air_defences(game, events=object()) == []

    game.settings.redfor_repairs_air_defences = True
    game.logistics.get_warehouse(cp.id).stock[SUPPLIES].quantity = 5
    assert redfor_repair_air_defences(game, events=object()) == []
    assert not launcher.alive
