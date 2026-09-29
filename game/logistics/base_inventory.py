"""What one base holds: warehouse stock and weapon stores.

Read-only summary used by the base window's "Base Inventory" tab
(qt_ui/windows/basemenu/inventory/QBaseInventory.py). Changing stock is done
in the Logistics window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from game.logistics import (
    new_base_warehouse,
    TransferStatus,
    Warehouse,
    WarehouseCategory,
)

if TYPE_CHECKING:
    from game import Game
    from game.logistics import LogisticsManager

#: Weapon inventory categories that are ground units, not weapons. The base
#: garrison is shown in the Ground Forces HQ tab, so they are left out here.
GROUND_UNIT_CATEGORIES = frozenset(
    {
        "Armour",
        "Air Defence",
        "Infantry Fighting Vehicle",
        "Artillery",
        "Support Vehicle",
        "Radar / Command",
        "Other Ground",
    }
)

#: A weapon with fewer than this many in store is shown as low: less than
#: one load for a four-ship flight of most aircraft.
LOW_WEAPON_QUANTITY = 10


@dataclass
class StockRow:
    category: WarehouseCategory
    quantity: float
    capacity: float

    @property
    def level(self) -> float:
        from game.logistics.levels import level

        return level(self.quantity, self.capacity)

    @property
    def needs_resupply(self) -> bool:
        """Same threshold as StockItem.needs_resupply (levels.LOW_LEVEL)."""
        from game.logistics.levels import LOW_LEVEL

        return self.level < LOW_LEVEL

    @property
    def label(self) -> str:
        return self.category.value.capitalize()


@dataclass
class WeaponRow:
    name: str
    quantity: int
    capacity: int
    #: Stock items merged into this row: the same weapon on different racks
    #: or launchers has its own DCS id, but is one weapon to the player.
    variants: int = 1

    @property
    def empty(self) -> bool:
        return self.quantity <= 0

    @property
    def low(self) -> bool:
        return not self.empty and self.quantity < LOW_WEAPON_QUANTITY


@dataclass
class BaseInventory:
    base_name: str
    is_main_base: bool
    stock: List[StockRow]
    #: Weapon category -> weapons, both sorted by name. None when the base's
    #: weapon stores have never been synced from the campaign.
    weapons: Optional[Dict[str, List[WeaponRow]]]
    #: Human-readable lines for supply flights heading to / leaving the base.
    incoming: List[str] = field(default_factory=list)
    outgoing: List[str] = field(default_factory=list)
    #: Naval munitions crates the base can hand out (ship rearming).
    naval_crates: int = 0
    #: Fuel the base's sorties used last mission, and how many turns the stock
    #: lasts at that rate (None: no sorties last mission). See logistics/fuel.py.
    fuel_used_last_mission: float = 0.0
    fuel_turns_left: Optional[float] = None
    unlimited_fuel: bool = False

    @property
    def weapon_totals(self) -> tuple[int, int, int]:
        """(weapon types, empty types, low types)."""
        rows = [r for rows in (self.weapons or {}).values() for r in rows]
        return (
            len(rows),
            sum(1 for r in rows if r.empty),
            sum(1 for r in rows if r.low),
        )


def weapon_rows(inventory: Any) -> Dict[str, List[WeaponRow]]:
    """Weapon category -> weapons, both sorted by name; ground units left out.

    The same weapon on different racks or launchers is one row.
    """
    weapons: Dict[str, List[WeaponRow]] = {}
    for category, items in inventory.items_by_category().items():
        if category in GROUND_UNIT_CATEGORIES:
            continue
        merged: Dict[str, WeaponRow] = {}
        for i in items:
            row = merged.get(i.name)
            if row is None:
                merged[i.name] = WeaponRow(i.name, int(i.quantity), int(i.capacity))
            else:
                row.quantity += int(i.quantity)
                row.capacity += int(i.capacity)
                row.variants += 1
        weapons[category] = sorted(merged.values(), key=lambda r: r.name)
    return weapons


def weapon_counts(inventory: Any) -> tuple[int, int, int]:
    """(weapon types, empty types, low types) of a base's weapon stores."""
    rows = [r for rows in weapon_rows(inventory).values() for r in rows]
    return (
        len(rows),
        sum(1 for r in rows if r.empty),
        sum(1 for r in rows if r.low),
    )


def base_inventory(game: Game, cp: Any) -> BaseInventory:
    """Everything the base holds, for display."""
    from game.logistics.naval_munitions import AMMO_PER_CRATE

    logistics: LogisticsManager = game.logistics
    warehouse = logistics.get_warehouse(cp.id)
    if warehouse is None:
        # Same default warehouse the Logistics window creates for a base.
        warehouse = new_base_warehouse(cp)
        logistics.add_warehouse(warehouse)

    stock = [
        StockRow(cat, warehouse.stock[cat].quantity, warehouse.stock[cat].capacity)
        for cat in WarehouseCategory
    ]

    weapons: Optional[Dict[str, List[WeaponRow]]] = None
    inventory = logistics.get_weapon_inventory(cp.id)
    if inventory is not None:
        weapons = weapon_rows(inventory)

    incoming: List[str] = []
    outgoing: List[str] = []
    names = {c.id: c.name for c in game.theater.controlpoints}
    for t in logistics._transfers.values():
        if t.status not in (TransferStatus.PLANNED, TransferStatus.IN_FLIGHT):
            continue
        state = "in flight" if t.status is TransferStatus.IN_FLIGHT else "planned"
        if t.dest_cp_id == cp.id:
            src = names.get(t.source_cp_id, "?")
            incoming.append(f"{t.cargo_label} from {src} ({state})")
        elif t.source_cp_id == cp.id:
            dst = names.get(t.dest_cp_id, "?")
            outgoing.append(f"{t.cargo_label} to {dst} ({state})")

    from game.logistics.fuel import turns_left, unlimited_fuel

    ammo = warehouse.stock[WarehouseCategory.AMMUNITION].quantity
    return BaseInventory(
        base_name=cp.name,
        is_main_base=logistics.is_main_base(cp.id),
        stock=stock,
        weapons=weapons,
        incoming=incoming,
        outgoing=outgoing,
        naval_crates=int(ammo // AMMO_PER_CRATE),
        fuel_used_last_mission=float(
            getattr(warehouse, "fuel_used_last_mission", 0.0) or 0.0
        ),
        fuel_turns_left=turns_left(warehouse),
        # Ships are supplied at sea: their fuel isn't tracked.
        unlimited_fuel=unlimited_fuel(game) or bool(getattr(cp, "is_fleet", False)),
    )
