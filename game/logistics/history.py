"""Warehouse stock per base, turn by turn.

One point per base per turn is recorded when the turn's mission is generated
(LogisticsManager.on_turn_end, after the turn's attrition), so each point is
what the base held going into that turn's mission. Regenerating the mission
replaces that turn's point. The Base Inventory tab draws the points as a chart
and adds the stock as it is now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List
from uuid import UUID

if TYPE_CHECKING:
    from game.logistics import LogisticsManager, Warehouse

#: Turns kept per base; older points are dropped.
MAX_TURNS = 200


@dataclass(frozen=True)
class HistoryPoint:
    turn: int
    fuel: float
    ammunition: float
    supplies: float
    troops: float
    #: Weapons in the base's weapon stores (all types together).
    weapons: int
    #: Fuel the base's sorties used in the mission before this point.
    fuel_used: float = 0.0


def _history(logistics: LogisticsManager) -> Dict[UUID, List[HistoryPoint]]:
    return logistics._history


def snapshot(logistics: Any, warehouse: Warehouse, turn: int) -> HistoryPoint:
    """What the warehouse (and the base's weapon stores) hold right now."""
    from game.logistics import WarehouseCategory

    stock = warehouse.stock
    inventory = logistics.get_weapon_inventory(warehouse.cp_id)
    weapons = sum(int(i.quantity) for i in inventory.items.values()) if inventory else 0
    return HistoryPoint(
        turn=turn,
        fuel=stock[WarehouseCategory.FUEL].quantity,
        ammunition=stock[WarehouseCategory.AMMUNITION].quantity,
        supplies=stock[WarehouseCategory.SUPPLIES].quantity,
        troops=stock[WarehouseCategory.TROOPS].quantity,
        weapons=weapons,
        fuel_used=float(getattr(warehouse, "fuel_used_last_mission", 0.0) or 0.0),
    )


def ensure_friendly_warehouses(game: Any) -> None:
    """Give every BLUEFOR base the default warehouse if it has none yet.

    Warehouses are otherwise created the first time a base is looked at
    (Base Inventory tab, Logistics window) or uses fuel, so a new campaign
    starts with none; the history and the map's supply layer need them.
    """
    from game.logistics import (
        keeps_warehouse,
        new_base_warehouse,
        upgrade_blue_fuel_capacity,
    )

    logistics = game.logistics
    for cp in game.theater.controlpoints:
        if not cp.captured.is_blue or not keeps_warehouse(cp):
            continue
        warehouse = logistics.get_warehouse(cp.id)
        if warehouse is None:
            logistics.add_warehouse(new_base_warehouse(cp))
        else:
            upgrade_blue_fuel_capacity(warehouse)


def record_turn(logistics: LogisticsManager, turn: int) -> None:
    """Record every warehouse's stock for this turn (replacing an earlier one)."""
    history = _history(logistics)
    for warehouse in logistics._warehouses.values():
        points = history.setdefault(warehouse.cp_id, [])
        if points and points[-1].turn == turn:
            points.pop()
        points.append(snapshot(logistics, warehouse, turn))
        del points[:-MAX_TURNS]


def history_for(logistics: LogisticsManager, cp_id: UUID) -> List[HistoryPoint]:
    """The base's recorded points, oldest first."""
    return list(_history(logistics).get(cp_id, []))


def forget_base(logistics: LogisticsManager, cp_id: UUID) -> None:
    _history(logistics).pop(cp_id, None)
