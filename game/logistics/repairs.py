"""Repairing ground units costs their base's warehouse stock.

BLUEFOR: the Repair button on a ground object (SAM site, EWR, armour group...)
still costs money, and now also supplies and, for weapons, ammunition from the
warehouse of the base the object belongs to. Without enough stock the repair
is refused.

    supplies     10 + the unit's price ($M)       Patriot launcher (15): 25
    ammunition   20 for launchers, TELARs, SHORAD, AAA and MANPADS; 0 else

REDFOR (with "REDFOR logistics" and "REDFOR repairs air defences" on): at the
end of every turn each damaged REDFOR SAM or EWR site that still has a unit
standing gets one destroyed unit back (radars first), paid for the same way
from its base's warehouse. A site with every unit destroyed is not rebuilt:
finishing a site off keeps it down, damaging it only buys time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

if TYPE_CHECKING:
    from game.logistics import Warehouse

logger = logging.getLogger(__name__)

SUPPLIES_BASE = 10.0
AMMO_FOR_WEAPONS = 20.0
#: REDFOR units brought back per damaged site per turn.
RED_REPAIRS_PER_SITE = 1


def _weapon_classes() -> Tuple[Any, ...]:
    from game.data.units import UnitClass

    return (
        UnitClass.LAUNCHER,
        UnitClass.TELAR,
        UnitClass.SHORAD,
        UnitClass.AAA,
        UnitClass.MANPAD,
    )


def _radar_classes() -> Tuple[Any, ...]:
    from game.data.units import UnitClass

    return (
        UnitClass.EARLY_WARNING_RADAR,
        UnitClass.SEARCH_RADAR,
        UnitClass.SEARCH_TRACK_RADAR,
        UnitClass.TRACK_RADAR,
        UnitClass.SPECIALIZED_RADAR,
    )


def repair_cost(unit: Any) -> Tuple[float, float]:
    """(supplies, ammunition) repairing this unit takes."""
    unit_type = getattr(unit, "unit_type", None)
    price = float(getattr(unit_type, "price", 0) or 0)
    unit_class = getattr(unit_type, "unit_class", None)
    ammo = AMMO_FOR_WEAPONS if unit_class in _weapon_classes() else 0.0
    return SUPPLIES_BASE + price, ammo


def _warehouse(game: Any, unit: Any) -> Optional[Warehouse]:
    cp = unit.ground_object.control_point
    logistics = getattr(game, "logistics", None)
    if logistics is None or getattr(cp, "is_fleet", False):
        return None
    return logistics.get_warehouse(cp.id)


def repair_shortfall(game: Any, unit: Any) -> Optional[str]:
    """Why the base can't pay for this repair, or None when it can.

    A base without a warehouse (ships, bases never looked at) pays nothing.
    """
    from game.logistics import WarehouseCategory

    warehouse = _warehouse(game, unit)
    if warehouse is None:
        return None
    supplies, ammo = repair_cost(unit)
    have_supplies = warehouse.stock[WarehouseCategory.SUPPLIES].quantity
    have_ammo = warehouse.stock[WarehouseCategory.AMMUNITION].quantity
    missing = []
    if have_supplies < supplies:
        missing.append(f"supplies ({have_supplies:.0f} of {supplies:.0f})")
    if have_ammo < ammo:
        missing.append(f"ammunition ({have_ammo:.0f} of {ammo:.0f})")
    if not missing:
        return None
    return "Not enough " + " and ".join(missing)


def charge_repair(game: Any, unit: Any) -> None:
    """Take the repair's supplies and ammunition from the unit's base."""
    from game.logistics import WarehouseCategory

    warehouse = _warehouse(game, unit)
    if warehouse is None:
        return
    supplies, ammo = repair_cost(unit)
    item = warehouse.stock[WarehouseCategory.SUPPLIES]
    item.quantity = max(0.0, item.quantity - supplies)
    item = warehouse.stock[WarehouseCategory.AMMUNITION]
    item.quantity = max(0.0, item.quantity - ammo)


def clear_wreck(game: Any, unit: Any) -> None:
    """Remove the wreck the repaired unit left (as the Repair button does)."""
    from dcs.mapping import Point

    try:
        destroyed = game.get_destroyed_units()
    except Exception:
        return
    for wreck in list(destroyed):
        p = Point(wreck["x"], wreck["z"], game.theater.terrain)
        if p.distance_to_point(unit.position) < 15:
            destroyed.remove(wreck)


def red_repairs_enabled(game: Any) -> bool:
    from game.logistics.redfor import enabled

    settings = getattr(game, "settings", None)
    return enabled(game) and bool(
        getattr(settings, "redfor_repairs_air_defences", False)
    )


def _repair_order(unit: Any) -> int:
    unit_type = getattr(unit, "unit_type", None)
    unit_class = getattr(unit_type, "unit_class", None)
    if unit_class in _radar_classes():
        return 0
    if unit_class in _weapon_classes():
        return 1
    return 2


def redfor_repair_air_defences(game: Any, events: Any) -> List[str]:
    """End of turn: REDFOR repairs its damaged SAM and EWR sites."""
    if not red_repairs_enabled(game):
        return []
    log: List[str] = []
    for tgo in game.theater.ground_objects:
        if getattr(tgo, "category", None) not in ("aa", "ewr"):
            continue
        if not tgo.control_point.captured.is_red:
            continue
        units = list(tgo.units)
        if not any(u.alive for u in units):
            continue  # destroyed sites stay down
        dead = sorted(
            (u for u in units if not u.alive and u.repairable), key=_repair_order
        )
        repaired = 0
        for unit in dead:
            if repaired >= RED_REPAIRS_PER_SITE:
                break
            if repair_shortfall(game, unit) is not None:
                break
            charge_repair(game, unit)
            if events is not None:
                unit.revive(events)
            else:
                unit.alive = True
            clear_wreck(game, unit)
            repaired += 1
            line = (
                f"REDFOR repaired {unit.unit_type or unit.type.id} at "
                f"{tgo.name} ({tgo.control_point.name})"
            )
            log.append(line)
            logger.info(line)
    return log
