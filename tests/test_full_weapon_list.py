"""Every base lists every weapon of the air wing, at 0 where it has none; only
the weapons its own squadrons carry count as empty or low."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from dcs.weapons_data import Weapons

from game import persistency

from game.dcs.aircrafttype import AircraftType
from game.logistics import (
    LogisticsManager,
    WeaponInventory,
    air_wing_weapons,
    build_weapon_inventory,
    complete_weapon_list,
    squadron_weapon_names,
)
from game.logistics.base_inventory import weapon_counts, weapon_rows

AIM_54 = str(Weapons.AIM_54A_Mk47["clsid"])  # Tomcat only


@pytest.fixture(autouse=True)
def _persistency(tmp_path: Path) -> None:
    persistency.setup(str(tmp_path), prefer_liberation_payloads=False, port=16884)


def _game() -> Any:
    hornet = AircraftType.named("F/A-18C Hornet (Lot 20)")
    tomcat = AircraftType.named("F-14A Tomcat (Block 135-GR Late)")
    home = SimpleNamespace(id=uuid.uuid4(), name="Home", base=SimpleNamespace(armor={}))
    other = SimpleNamespace(
        id=uuid.uuid4(), name="Other", base=SimpleNamespace(armor={})
    )
    squadrons = {
        hornet: [SimpleNamespace(location=home)],
        tomcat: [SimpleNamespace(location=other)],
    }
    game = SimpleNamespace(
        blue=SimpleNamespace(air_wing=SimpleNamespace(squadrons=squadrons)),
        logistics=LogisticsManager(),
    )
    return game, home, other


def _hornet_weapon(game: Any, home: Any) -> str:
    """A weapon the Hornet (at Home) carries and the Tomcat doesn't."""
    from game.data.weapons import Pylon

    hornet, tomcat = list(game.blue.air_wing.squadrons)
    tomcat_ids = {w.clsid for p in Pylon.iter_pylons(tomcat) for w in p.allowed}
    return sorted(
        w.clsid
        for p in Pylon.iter_pylons(hornet)
        for w in p.allowed
        if w.clsid not in tomcat_ids
    )[0]


def test_every_air_wing_weapon_is_listed_at_every_base() -> None:
    game, home, other = _game()
    everything = air_wing_weapons(game)
    hornet_weapon = _hornet_weapon(game, home)
    assert AIM_54 in everything and hornet_weapon in everything
    inv = build_weapon_inventory(home, game)
    assert set(everything) <= set(inv.items)
    assert inv.items[AIM_54].quantity == 0, "no Tomcat at Home: listed at 0"
    assert inv.items[hornet_weapon].quantity > 0, "the Hornet's weapons have stock"


def test_existing_stock_is_kept_and_only_missing_weapons_are_added() -> None:
    game, home, _ = _game()
    inv = WeaponInventory(cp_id=home.id, cp_name="Home")
    inv.add_item(AIM_54, "AIM-54A", "Air-to-Air Missile", 40)
    added = complete_weapon_list(game, inv)
    assert added == len(air_wing_weapons(game)) - 1
    assert inv.items[AIM_54].quantity == 40
    assert complete_weapon_list(game, inv) == 0, "nothing twice"


def test_only_the_squadrons_weapons_count_as_empty() -> None:
    game, home, _ = _game()
    gbu = _hornet_weapon(game, home)
    inv = build_weapon_inventory(home, game)
    for item in inv.items.values():
        if item.name == inv.items[gbu].name:
            item.quantity = 0  # the Hornet ran out of it
    used = squadron_weapon_names(game, home)
    assert used is not None
    assert inv.items[gbu].name in used
    assert inv.items[AIM_54].name not in used

    rows = {r.name: r for rs in weapon_rows(inv, used).values() for r in rs}
    tomcat_row = rows[inv.items[AIM_54].name]
    assert not tomcat_row.used_here and not tomcat_row.empty
    assert rows[inv.items[gbu].name].empty

    types, empty, _ = weapon_counts(inv, used)
    hornet_rows = {r.name for r in rows.values() if r.used_here}
    assert types == len(hornet_rows)
    assert empty >= 1
    # Without the base's squadrons every listed weapon would count as empty.
    _, empty_all, _ = weapon_counts(inv)
    assert empty_all > empty + 50


def test_full_restock_fills_only_the_squadrons_weapons_and_stock() -> None:
    game, home, _ = _game()
    gbu = _hornet_weapon(game, home)
    lm = game.logistics
    inv = build_weapon_inventory(home, game)
    lm.set_weapon_inventory(inv)
    used = squadron_weapon_names(game, home)
    cost_all = lm.restock_inventory_cost(home.id)
    cost_here = lm.restock_inventory_cost(home.id, used)
    assert 0 < cost_here < cost_all
    lm.restock_inventory(home.id, used)
    assert inv.items[AIM_54].quantity == 0, "Tomcat missiles not bought for Home"
    assert inv.items[gbu].quantity == inv.items[gbu].capacity
