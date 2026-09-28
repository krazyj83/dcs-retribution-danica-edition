"""How well supplied each friendly base is, for the map's "Base supply" layer.

Each BLUEFOR base gets a status from its fuel and ammunition:

    critical  fuel or ammunition empty, or fuel for less than 1 more turn
    low       fuel or ammunition under 40% (the resupply threshold), or fuel
              for less than 3 more turns at the last mission's rate
    ok        everything else

With "Unlimited warehouse fuel" on, fuel only counts when it is empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from game import Game

LOW_LEVEL = 0.40
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


def classify(
    fuel_level: float,
    ammo_level: float,
    turns_left: Optional[float],
    unlimited: bool,
) -> tuple[str, List[str]]:
    """(status, reasons) from stock levels (0..1) and fuel turns left."""
    critical: List[str] = []
    low: List[str] = []
    if fuel_level <= 0:
        critical.append("out of fuel")
    elif not unlimited:
        if turns_left is not None and turns_left < CRITICAL_TURNS:
            critical.append("fuel for less than 1 turn")
        elif turns_left is not None and turns_left < LOW_TURNS:
            low.append(f"fuel for {turns_left:.1f} turns")
        if fuel_level < LOW_LEVEL:
            low.append(f"fuel {fuel_level:.0%}")
    if ammo_level <= 0:
        critical.append("out of ammunition")
    elif ammo_level < LOW_LEVEL:
        low.append(f"ammunition {ammo_level:.0%}")
    if critical:
        return "critical", critical + low
    if low:
        return "low", low
    return "ok", []


def _level(quantity: float, capacity: float) -> float:
    return 0.0 if capacity <= 0 else quantity / capacity


def supply_status(game: Game) -> List[BaseSupply]:
    """Supply status of every BLUEFOR base (bases not yet given a warehouse
    show the default one, as the Base Inventory tab does)."""
    from game.logistics import Warehouse, WarehouseCategory
    from game.logistics.fuel import turns_left, unlimited_fuel
    from game.theater.controlpoint import OffMapSpawn

    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return []
    unlimited = unlimited_fuel(game)
    result: List[BaseSupply] = []
    for cp in game.theater.controlpoints:
        if not cp.captured.is_blue or isinstance(cp, OffMapSpawn):
            continue
        warehouse = logistics.get_warehouse(cp.id)
        if warehouse is None:
            warehouse = Warehouse(cp_id=cp.id, cp_name=cp.name)
        fuel = warehouse.stock[WarehouseCategory.FUEL]
        ammo = warehouse.stock[WarehouseCategory.AMMUNITION]
        supplies = warehouse.stock[WarehouseCategory.SUPPLIES]
        left = turns_left(warehouse)
        status, reasons = classify(
            _level(fuel.quantity, fuel.capacity),
            _level(ammo.quantity, ammo.capacity),
            left,
            unlimited,
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
    return result
