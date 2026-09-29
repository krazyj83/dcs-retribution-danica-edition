"""Warehouse fuel used by sorties.

After each mission, every BLUEFOR aircraft planned in that mission uses fuel
from its departure base's warehouse: its internal fuel (DCS value) at
FUEL_KG_PER_UNIT kg per warehouse unit, at most MAX_UNITS_PER_AIRCRAFT.

    F-16C       3,249 kg  -> 16 units
    A-10C       5,029 kg  -> 25 units
    C-130J     19,692 kg  -> 98 units
    KC-135     90,700 kg  -> 100 units (capped)
    UH-1H         631 kg  ->  3 units

What each base used is kept, so the Base Inventory tab can show how many
turns the stock lasts at that rate. A base that runs dry only gets a
warning: flights can still be planned.

Setting "Unlimited warehouse fuel" turns this off (and the 1% per turn fuel
attrition): fuel then only goes down when fuel depots are destroyed.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from game import Game
    from game.logistics import Warehouse

FUEL_KG_PER_UNIT = 200.0
MAX_UNITS_PER_AIRCRAFT = 100.0


def unlimited_fuel(game: Any) -> bool:
    settings = getattr(game, "settings", None)
    return bool(getattr(settings, "logistics_unlimited_fuel", False))


def fuel_per_aircraft(aircraft_type: Any) -> float:
    """Warehouse fuel one sortie of this aircraft uses."""
    dcs_type = getattr(aircraft_type, "dcs_unit_type", None)
    kg = float(getattr(dcs_type, "fuel_max", 0) or 0)
    return min(MAX_UNITS_PER_AIRCRAFT, kg / FUEL_KG_PER_UNIT)


def turns_left(warehouse: Warehouse) -> Optional[float]:
    """How many more turns the fuel lasts at the last mission's rate.

    None when the base used no fuel last mission (nothing to go by).
    """
    from game.logistics import WarehouseCategory

    used = float(getattr(warehouse, "fuel_used_last_mission", 0.0) or 0.0)
    if used <= 0:
        return None
    return warehouse.stock[WarehouseCategory.FUEL].quantity / used


def fuel_warning(game: Any, base: Any) -> Optional[str]:
    """Warning for flights planned from ``base``, or None when fuel is fine.

    Only a warning: flights can still be planned from a base with no fuel.
    """
    from game.logistics import WarehouseCategory

    if unlimited_fuel(game) or not base.captured.is_blue:
        return None
    if getattr(base, "is_fleet", False):
        return None  # supplied at sea
    logistics = getattr(game, "logistics", None)
    warehouse = logistics.get_warehouse(base.id) if logistics else None
    if warehouse is None:
        return None
    fuel = warehouse.stock[WarehouseCategory.FUEL].quantity
    if fuel <= 0:
        return f"{base.name} is out of fuel: resupply it before relying on it."
    left = turns_left(warehouse)
    if left is not None and left < 1:
        return f"{base.name} fuel is low: less than one more turn at this rate."
    return None


def use_fuel_for_sorties(game: Game) -> List[str]:
    """Take the fuel for every BLUEFOR aircraft of the mission just flown.

    Runs after the mission results are committed (captures applied) and before
    the ATO is cleared. Returns log lines.
    """
    from game.logistics import (
        Warehouse,
        WarehouseCategory,
        keeps_warehouse,
        new_base_warehouse,
    )

    logistics = game.logistics
    for wh in logistics._warehouses.values():
        wh.fuel_used_last_mission = 0.0
    blue = getattr(game, "blue", None)
    if unlimited_fuel(game) or blue is None:
        return []

    used: Dict[Any, float] = defaultdict(float)
    sorties: Dict[Any, int] = defaultdict(int)
    bases: Dict[Any, Any] = {}
    for package in blue.ato.packages:
        for flight in package.flights:
            base = getattr(flight, "departure", None)
            if base is None or not base.captured.is_blue:
                continue  # lost during the mission: its stock went with it
            if not keeps_warehouse(base):
                continue  # carriers, LHAs and off-map spawns: no warehouse
            bases[base.id] = base
            used[base.id] += flight.count * fuel_per_aircraft(flight.unit_type)
            sorties[base.id] += flight.count

    log: List[str] = []
    for base_id, amount in used.items():
        base = bases[base_id]
        if amount <= 0:
            continue
        found = logistics.get_warehouse(base.id)
        if found is None:
            found = new_base_warehouse(base)
            logistics.add_warehouse(found)
        warehouse: Warehouse = found
        fuel = warehouse.stock[WarehouseCategory.FUEL]
        before = fuel.quantity
        fuel.quantity = max(0.0, before - amount)
        warehouse.fuel_used_last_mission = amount
        line = (
            f"{base.name}: {sorties[base_id]} sortie(s) used {before - fuel.quantity:.0f} "
            f"fuel, {fuel.quantity:.0f} left"
        )
        if fuel.quantity <= 0:
            line += " — OUT OF FUEL"
        else:
            line += f" (about {fuel.quantity / amount:.1f} turns at this rate)"
        log.append(line)
    return log


# ── Fuel trucks ───────────────────────────────────────────────────────────
#
# A fuel truck in a convoy (a player-drawn route or a unit transfer) carries
# fuel from the base it left (the origin) to where it arrives. The fuel leaves
# the origin's warehouse when the truck arrives (and is added to the arrival
# base, up to its capacity; what doesn't fit stays at the origin) or when the
# truck is destroyed (the load is lost). REDFOR bases keep warehouse fuel only
# with the "REDFOR logistics" setting on; otherwise their trucks are just
# vehicles. REDFOR lines go to the log, not the player's debrief.

#: Warehouse fuel one truck carries, by DCS type (200 kg per unit, ~0.8 kg/l).
FUEL_TRUCK_LOADS: Dict[str, float] = {
    "M978 HEMTT Tanker": 38.0,  # ~9,500 l
    "ATZ-10": 40.0,  # ~10,000 l
    "ATZ-5": 20.0,  # ~5,000 l
    "ATMZ-5": 20.0,  # ~5,000 l
    "ATZ-60_Maz": 240.0,  # ~60,000 l trailer
    "TRM2000_Citerne": 40.0,  # mod unit
}

#: Fuel trucks added to a convoy on top of its other vehicles, when the base
#: has spare ones.
MAX_FUEL_TRUCKS_PER_CONVOY = 2


def truck_load(unit_type: Any) -> float:
    """Fuel one truck of this ground unit type carries (0: not a fuel truck)."""
    dcs_type = getattr(unit_type, "dcs_unit_type", None)
    return FUEL_TRUCK_LOADS.get(str(getattr(dcs_type, "id", "")), 0.0)


def is_fuel_truck(unit_type: Any) -> bool:
    return truck_load(unit_type) > 0


def _fuel_stock(game: Any, base: Any) -> Any:
    """The base's fuel StockItem, creating the default warehouse if needed.

    None for bases that don't keep warehouse fuel (not BLUEFOR).
    """
    from game.logistics import Warehouse, WarehouseCategory, new_base_warehouse

    from game.logistics.redfor import enabled as redfor_enabled

    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return None
    if not base.captured.is_blue and not (
        base.captured.is_red and redfor_enabled(game)
    ):
        return None
    warehouse = logistics.get_warehouse(base.id)
    if warehouse is None:
        warehouse = new_base_warehouse(base)
        logistics.add_warehouse(warehouse)
    return warehouse.stock[WarehouseCategory.FUEL]


def deliver_truck_fuel(
    game: Any,
    origin: Any,
    arrival: Any,
    unit_type: Any,
    count: int = 1,
    side: Any = None,
) -> Optional[str]:
    """Fuel trucks from origin arrived at arrival: move their fuel.

    ``side`` is the convoy's owner. Nothing moves when the origin or the
    arrival base no longer belongs to it (a base changed hands on the way):
    the fuel isn't the convoy's own side's any more.
    """
    load = truck_load(unit_type) * count
    if load <= 0 or origin is arrival:
        return None
    owner = side if side is not None else origin.captured
    if origin.captured != owner or arrival.captured != owner:
        return None
    source = _fuel_stock(game, origin)
    target = _fuel_stock(game, arrival)
    if source is None or target is None:
        return None
    carried = min(load, source.quantity)
    fits = min(carried, max(0.0, target.capacity - target.quantity))
    source.quantity -= fits
    target.quantity += fits
    line = (
        f"{count} fuel truck(s) from {origin.name} delivered {fits:.0f} fuel "
        f"to {arrival.name}"
    )
    if fits < load:
        line += f" (of {load:.0f}: {origin.name} had {carried:.0f}"
        line += ", the rest did not fit)" if fits < carried else ")"
    _log(game, line, red=origin.captured.is_red)
    return line


def lose_truck_fuel(
    game: Any, origin: Any, unit_type: Any, count: int = 1, side: Any = None
) -> Optional[str]:
    """Fuel trucks from origin were destroyed: their load is lost.

    Not when the origin now belongs to the other side (``side`` is the
    convoy's owner): the enemy's fuel was never on the trucks.
    """
    if side is not None and origin.captured != side:
        return None
    load = truck_load(unit_type) * count
    source = _fuel_stock(game, origin) if load > 0 else None
    if source is None:
        return None
    lost = min(load, source.quantity)
    source.quantity -= lost
    line = f"{count} fuel truck(s) from {origin.name} destroyed: {lost:.0f} fuel lost"
    _log(game, line, red=origin.captured.is_red)
    return line


def _log(game: Any, line: str, red: bool = False) -> None:
    if red:
        import logging

        logging.getLogger(__name__).info(f"REDFOR: {line}")
        return
    logistics = getattr(game, "logistics", None)
    if logistics is not None and hasattr(logistics, "add_debrief_log"):
        logistics.add_debrief_log([line])
