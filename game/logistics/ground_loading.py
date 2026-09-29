"""Player aircraft load their weapons and fuel from the base's stores in DCS.

With "Player aircraft load from base stores" on (default), player (client)
aircraft of a BLUEFOR flight that starts on the ground at an airfield spawn
with empty pylons and EMPTY_FUEL_FRACTION of their internal fuel. The player
loads them with the ground crew (rearm/refuel), and DCS takes what they load
from the airfield's DCS warehouse, which is filled from Retribution's stock:

* Fuel: the warehouse's jet fuel is set to the base's warehouse fuel
  (FUEL_KG_PER_UNIT kg per unit) and made limited, unless "Unlimited warehouse
  fuel" is on.
* Weapons: the warehouse's munitions are made limited, and at mission start
  the mission script (dcs_retribution.lua) sets every DCS weapon to what the
  base's weapon stores hold. Retribution counts stores as they hang on a pylon
  (a rack of 2 GBU-12 is one store), DCS counts single weapons, so each store
  is matched by name to a DCS weapon and counted times the rack size. DCS
  weapons no store matches are set to UNMATCHED_STOCK so they can still be
  loaded.

What a player aircraft carried is counted by the mission script (weapons on
board at takeoff less on landing, or everything if it was lost) and taken from
the weapon stores after the mission (logistics/weapon_use.py). AI aircraft,
and players starting at FOBs, FARPs, carriers or in the air, keep their
planned loadouts, charged as before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from game import Game

logger = logging.getLogger(__name__)

EMPTY_FUEL_FRACTION = 0.10
UNMATCHED_STOCK = 500


def enabled(game: Any) -> bool:
    settings = getattr(game, "settings", None)
    return bool(getattr(settings, "logistics_players_load_on_ground", False))


def is_ground_loading_base(cp: Any) -> bool:
    """A friendly airfield (not a FOB, FARP or ship)."""
    from game.theater.controlpoint import Airfield

    return isinstance(cp, Airfield) and cp.captured.is_blue


def applies_to(game: Any, flight: Any, member: Any) -> bool:
    """Does this flight member spawn empty and load on the ground?"""
    from game.ato.starttype import StartType

    if not enabled(game) or not getattr(member, "is_player", False):
        return False
    if flight.start_type is StartType.IN_FLIGHT:
        return False
    return is_ground_loading_base(flight.departure)


def empty_fuel(unit_type: Any) -> float:
    """Fuel (kg) a ground-loading aircraft spawns with."""
    fuel_max = float(getattr(unit_type.dcs_unit_type, "fuel_max", 0) or 0)
    return max(100.0, fuel_max * EMPTY_FUEL_FRACTION)


def _airport_bases(game: Game) -> List[Any]:
    if not enabled(game):
        return []
    return [cp for cp in game.theater.controlpoints if is_ground_loading_base(cp)]


def configure_airports(game: Game, mission: Any) -> None:
    """Limit fuel and munitions of the DCS warehouses of friendly airfields."""
    from game.logistics import WarehouseCategory
    from game.logistics.fuel import FUEL_KG_PER_UNIT, unlimited_fuel

    for cp in _airport_bases(game):
        airport = mission.terrain.airports.get(cp.airport.name)
        warehouse = game.logistics.get_warehouse(cp.id)
        if airport is None or warehouse is None:
            continue
        if not unlimited_fuel(game):
            fuel_units = warehouse.stock[WarehouseCategory.FUEL].quantity
            airport.unlimited_fuel = False
            airport.jet_init = round(fuel_units * FUEL_KG_PER_UNIT / 1000.0, 1)
        if game.logistics.get_weapon_inventory(cp.id) is not None:
            airport.unlimited_munitions = False


def script_data(game: Game) -> Dict[str, Any]:
    """dcsRetributionWarehouses: each airfield's stores for the mission script."""
    from game.logistics import WarehouseCategory
    from game.logistics.fuel import FUEL_KG_PER_UNIT, unlimited_fuel
    from game.logistics.weapon_use import _norm, _pydcs_ids, weapons_per_store

    bases: List[Dict[str, Any]] = []
    for cp in _airport_bases(game):
        inventory = game.logistics.get_weapon_inventory(cp.id)
        warehouse = game.logistics.get_warehouse(cp.id)
        if inventory is None:
            continue
        stores = []
        for item in inventory.items.values():
            if item.quantity <= 0 or item.clsid not in _pydcs_ids():
                continue
            stores.append(
                {
                    "key": _norm(item.name) + "|" + _norm(_pydcs_ids()[item.clsid]),
                    "per_store": weapons_per_store(item.name),
                    "count": int(item.quantity),
                }
            )
        fuel: Optional[float] = None
        if warehouse is not None and not unlimited_fuel(game):
            fuel = warehouse.stock[WarehouseCategory.FUEL].quantity * FUEL_KG_PER_UNIT
        bases.append({"airbase": cp.airport.name, "stores": stores, "fuel_kg": fuel})
    return {"bases": bases, "unmatched": UNMATCHED_STOCK}
