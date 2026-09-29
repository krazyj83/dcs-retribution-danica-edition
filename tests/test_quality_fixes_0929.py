"""Fixes from the 29 Sep quality check."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from game.dcs.groundunittype import GroundUnitType
from game.logistics import (
    LogisticsManager,
    Warehouse,
    WarehouseCategory,
    WeaponStockItem,
    item_restock_cost,
    keeps_warehouse,
    new_base_warehouse,
)
from game.logistics.capture import on_base_captured
from game.logistics.fuel import deliver_truck_fuel, lose_truck_fuel
from game.theater.player import Player

FUEL, AMMO = WarehouseCategory.FUEL, WarehouseCategory.AMMUNITION
ATZ10 = GroundUnitType.named("Fuel Truck ATZ-10")


def _wh(logistics: Any, cp_id: Any) -> Warehouse:
    wh = logistics.get_warehouse(cp_id)
    assert wh is not None
    return wh


def _cp(name: str, side: Player = Player.BLUE, **extra: Any) -> Any:
    return SimpleNamespace(id=uuid4(), name=name, captured=side, **extra)


def test_one_restock_price_for_items_and_whole_stores() -> None:
    item = WeaponStockItem(name="AIM-120C", clsid="x", category="Air-to-Air")
    item.quantity, item.capacity = 50, 250
    assert item_restock_cost(item) == 2.0  # 200 x $0.01M
    logistics = LogisticsManager()
    from game.logistics import WeaponInventory

    base = _cp("Larnaca")
    inv = WeaponInventory(cp_id=base.id, cp_name=base.name)
    inv.items["x"] = item
    logistics.set_weapon_inventory(inv)
    assert logistics.restock_inventory_cost(base.id) == 2.0


def test_warehouses_are_made_per_side() -> None:
    blue = new_base_warehouse(_cp("Batumi"))
    red = new_base_warehouse(_cp("Maykop", Player.RED))
    assert blue.coalition == "blue" and blue.stock[FUEL].quantity == 2000
    assert blue.stock[AMMO].capacity == 1000
    assert red.coalition == "red" and red.stock[AMMO].quantity == 2000


def test_capture_fits_the_warehouse_to_the_new_owner() -> None:
    base = _cp("Kobuleti")
    logistics = LogisticsManager()
    logistics.add_warehouse(new_base_warehouse(base))

    on_base_captured(logistics, base, Player.RED)
    wh = logistics.get_warehouse(base.id)
    assert wh is not None and wh.coalition == "red"
    assert wh.stock[AMMO].capacity == 2000  # REDFOR capacity, not the old 1000
    assert wh.stock[FUEL].quantity == 2000  # fuel kept

    on_base_captured(logistics, base, Player.BLUE)
    assert wh.coalition == "blue" and wh.stock[AMMO].capacity == 1000


def test_ships_and_off_map_spawns_keep_no_warehouse() -> None:
    from game.theater.controlpoint import OffMapSpawn

    assert keeps_warehouse(_cp("Kutaisi", is_fleet=False))
    assert not keeps_warehouse(_cp("CVN-74", is_fleet=True))
    assert not keeps_warehouse(OffMapSpawn.__new__(OffMapSpawn))


def _truck_game(*bases: Any) -> Any:
    logistics = LogisticsManager()
    for base in bases:
        logistics.add_warehouse(new_base_warehouse(base))
    return SimpleNamespace(
        logistics=logistics, settings=SimpleNamespace(redfor_logistics=True)
    )


def test_fuel_trucks_do_nothing_after_their_origin_changed_hands() -> None:
    home, forward = _cp("Home"), _cp("Forward")
    game = _truck_game(home, forward)
    home.captured = Player.RED  # captured while the convoy was on the road

    assert deliver_truck_fuel(game, home, forward, ATZ10, side=Player.BLUE) is None
    assert lose_truck_fuel(game, home, ATZ10, side=Player.BLUE) is None
    assert _wh(game.logistics, home.id).stock[FUEL].quantity == 2000


def test_removing_a_drop_zone_refunds_its_planned_cargo() -> None:
    from game.logistics import DropZone, DropZoneType, TransferStatus

    source, dest = _cp("Larnaca"), _cp("Paphos")
    logistics = LogisticsManager()
    for base in (source, dest):
        logistics.add_warehouse(Warehouse(cp_id=base.id, cp_name=base.name))
    dz = DropZone(
        name="DZ",
        dz_type=DropZoneType.CARGO,
        lat=0,
        lon=0,
        cp_id=dest.id,
        coalition="blue",
    )
    logistics.add_drop_zone(dz)
    t = logistics.schedule_transfer(source.id, dest.id, dz.dz_id, AMMO, 100, "UH-1H", 1)
    assert t is not None
    assert _wh(logistics, source.id).stock[AMMO].quantity == 400

    logistics.remove_drop_zone(dz.dz_id)

    assert t.status is TransferStatus.FAILED
    assert _wh(logistics, source.id).stock[AMMO].quantity == 500


def test_red_stock_takes_no_attrition(monkeypatch: Any) -> None:
    blue, red = _cp("Batumi"), _cp("Maykop", Player.RED)
    logistics = LogisticsManager()
    logistics.add_warehouse(new_base_warehouse(blue))
    logistics.add_warehouse(new_base_warehouse(red))
    game: Any = SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(logistics_unlimited_fuel=False),
        theater=SimpleNamespace(controlpoints=[blue, red]),
        turn=2,
    )
    monkeypatch.setattr(
        "game.logistics.transfer_flights.flight_for_transfer", lambda *a: None
    )
    logistics.on_turn_end(game)
    assert _wh(logistics, blue.id).stock[FUEL].quantity == 1980
    assert _wh(logistics, red.id).stock[FUEL].quantity == 2000


def test_ground_loading_leaves_fuel_unlimited_with_the_setting() -> None:
    from game.logistics.ground_loading import configure_airports, script_data
    from game.theater.controlpoint import Airfield

    class _Field(Airfield):
        captured = None  # type: ignore[assignment]

    cp: Any = _Field.__new__(_Field)
    cp.id, cp.name, cp.captured = uuid4(), "Kutaisi", Player.BLUE
    cp.airport = SimpleNamespace(name="Kutaisi")
    logistics = LogisticsManager()
    logistics.add_warehouse(new_base_warehouse(cp))
    from game.logistics import WeaponInventory

    logistics.set_weapon_inventory(WeaponInventory(cp_id=cp.id, cp_name=cp.name))
    game: Any = SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(
            logistics_players_load_on_ground=True, logistics_unlimited_fuel=True
        ),
        theater=SimpleNamespace(controlpoints=[cp]),
    )
    airport = SimpleNamespace(unlimited_fuel=True, unlimited_munitions=True)
    configure_airports(
        game, SimpleNamespace(terrain=SimpleNamespace(airports={"Kutaisi": airport}))
    )
    assert airport.unlimited_fuel is True and airport.unlimited_munitions is False
    assert script_data(game)["bases"][0]["fuel_kg"] is None


def test_depot_damage_is_applied_once_with_the_results() -> None:
    from game.logistics.debrief_hook import (
        apply_damage,
        update_logistics_from_debriefing,
    )

    base = _cp("Batumi")
    logistics = LogisticsManager()
    logistics.add_warehouse(new_base_warehouse(base))
    depot = SimpleNamespace(
        theater_unit=SimpleNamespace(
            ground_object=SimpleNamespace(category="fuel", control_point=base)
        )
    )
    debriefing: Any = SimpleNamespace(
        game=SimpleNamespace(logistics=logistics), ground_object_losses=[depot]
    )

    apply_damage(debriefing)  # at results time
    lines = update_logistics_from_debriefing(debriefing)  # debrief window

    assert _wh(logistics, base.id).stock[FUEL].quantity == 1850
    assert any("fuel depot destroyed" in line for line in lines)
