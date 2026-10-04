"""How well supplied each friendly base is, for the map's "Base supply" layer.

Each BLUEFOR base gets a status from its fuel, its ammunition (bulk
munitions: ship crates, repairs) and its weapon stores (the aircraft's
missiles and bombs), with the thresholds of logistics/levels.py:

    critical  fuel or ammunition under 20% or empty, fuel for less than 1
              more turn, or half the weapon types in store empty
    low       fuel or ammunition under 40% (the resupply threshold), fuel for
              less than 3 more turns at the last mission's rate, or any
              weapon type in store empty
    ok        everything else

With "Unlimited warehouse fuel" on, fuel only counts when it is empty.

REDFOR bases are shown only while there is a recent recon report on them
(logistics/intel.py): their amounts are the report's levels in percent, and
intel_age says how many turns old it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from game import Game

from game.logistics.levels import LOW_LEVEL  # noqa: F401  (kept for importers)

CRITICAL_TURNS = 1.0
LOW_TURNS = 3.0


@dataclass
class BaseSupply:
    cp: Any
    fuel: float
    fuel_capacity: float
    ammunition: float
    ammunition_capacity: float
    supplies: float
    supplies_capacity: float
    fuel_turns_left: Optional[float]
    unlimited_fuel: bool
    status: str
    reasons: List[str]
    side: str = "blue"
    #: REDFOR only: turns since the recon report the numbers come from.
    intel_age: Optional[int] = None


def classify(
    fuel_level: float,
    ammo_level: float,
    turns_left: Optional[float],
    unlimited: bool,
    weapon_types: int = 0,
    weapons_empty: int = 0,
) -> tuple[str, List[str]]:
    """(status, reasons) from stock levels (0..1), fuel turns left and the
    weapon stores (types tracked, types empty)."""
    from game.logistics.levels import level_status

    critical: List[str] = []
    low: List[str] = []

    fuel = level_status(fuel_level)
    if fuel == "empty":
        critical.append("out of fuel")
    elif not unlimited:
        if fuel == "critical":
            critical.append(f"fuel {fuel_level:.0%}")
        elif fuel == "low":
            low.append(f"fuel {fuel_level:.0%}")
        if turns_left is not None and turns_left < CRITICAL_TURNS:
            critical.append("fuel for less than 1 turn")
        elif turns_left is not None and turns_left < LOW_TURNS:
            low.append(f"fuel for {turns_left:.1f} turns")

    ammo = level_status(ammo_level)
    if ammo == "empty":
        critical.append("out of ammunition")
    elif ammo == "critical":
        critical.append(f"ammunition {ammo_level:.0%}")
    elif ammo == "low":
        low.append(f"ammunition {ammo_level:.0%}")

    if weapons_empty > 0:
        line = f"{weapons_empty} weapon type(s) empty"
        if weapon_types and weapons_empty * 2 >= weapon_types:
            critical.append(line)
        else:
            low.append(line)

    if critical:
        return "critical", critical + low
    if low:
        return "low", low
    return "ok", []


def _level(quantity: float, capacity: float) -> float:
    from game.logistics.levels import level

    return level(quantity, capacity)


def supply_status(game: Game) -> List[BaseSupply]:
    """Supply status of every BLUEFOR base (bases not yet given a warehouse
    show the default one, as the Base Inventory tab does)."""
    from game.logistics import WarehouseCategory, keeps_warehouse, new_base_warehouse
    from game.logistics.base_inventory import weapon_counts
    from game.logistics.fuel import turns_left, unlimited_fuel

    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return []
    unlimited = unlimited_fuel(game)
    result: List[BaseSupply] = []
    for cp in game.theater.controlpoints:
        if not cp.captured.is_blue or not keeps_warehouse(cp):
            continue
        warehouse = logistics.get_warehouse(cp.id)
        if warehouse is None:
            warehouse = new_base_warehouse(cp)
        fuel = warehouse.stock[WarehouseCategory.FUEL]
        ammo = warehouse.stock[WarehouseCategory.AMMUNITION]
        supplies = warehouse.stock[WarehouseCategory.SUPPLIES]
        left = turns_left(warehouse)
        inventory = logistics.get_weapon_inventory(cp.id)
        from game.logistics import squadron_weapon_names

        types, empty, _ = (
            weapon_counts(inventory, squadron_weapon_names(game, cp))
            if inventory
            else (0, 0, 0)
        )
        status, reasons = classify(
            _level(fuel.quantity, fuel.capacity),
            _level(ammo.quantity, ammo.capacity),
            left,
            unlimited,
            weapon_types=types,
            weapons_empty=empty,
        )
        result.append(
            BaseSupply(
                cp=cp,
                fuel=fuel.quantity,
                fuel_capacity=fuel.capacity,
                ammunition=ammo.quantity,
                ammunition_capacity=ammo.capacity,
                supplies=supplies.quantity,
                supplies_capacity=supplies.capacity,
                fuel_turns_left=left,
                unlimited_fuel=unlimited,
                status=status,
                reasons=reasons,
            )
        )
    result.extend(_enemy_bases_from_intel(game))
    return result


def _enemy_bases_from_intel(game: Any) -> List[BaseSupply]:
    from game.logistics.intel import intel_for
    from game.logistics.redfor import enabled, is_red_land_base

    if not enabled(game):
        return []
    rows: List[BaseSupply] = []
    for cp in game.theater.controlpoints:
        if not is_red_land_base(cp):
            continue
        found = intel_for(game, cp)
        if found is None:
            continue
        report, age = found
        status, reasons = classify(report.fuel, report.ammunition, None, False)
        rows.append(
            BaseSupply(
                cp=cp,
                fuel=report.fuel * 100,
                fuel_capacity=100,
                ammunition=report.ammunition * 100,
                ammunition_capacity=100,
                supplies=report.supplies * 100,
                supplies_capacity=100,
                fuel_turns_left=None,
                unlimited_fuel=False,
                status=status,
                reasons=reasons,
                side="red",
                intel_age=age,
            )
        )
    return rows


def notify_changed() -> None:
    """Tell the map that base stock changed, so it reloads the supply rings.

    Called by the windows that change stock mid-turn; new turns and game loads
    reload the rings anyway.
    """
    from game.server import EventStream
    from game.sim import GameUpdateEvents

    EventStream.put_nowait(GameUpdateEvents().update_supply_status())
