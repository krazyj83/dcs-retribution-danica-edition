"""
game/logistics/warehouse.py

Warehouse inventory model. Each ControlPoint (airbase, FARP, road base)
has one Warehouse that tracks stockpiles of supplies across categories:
ammunition, fuel, spare parts, troops, and vehicles.

Key features:
  - add / consume / transfer stock between warehouses
  - export snapshot to dict (saved in campaign JSON each turn)
  - import from previous snapshot (rollover — preserves stock across turns)
  - spoilage: perishable items decay by a configurable % if not used

Concept — why a Warehouse matters in campaign play:
  Without a warehouse model, every base magically has infinite supplies.
  With it, the player must think about airlift routes (cargo drop zones)
  to keep forward FARPs stocked. Running a FARP dry stops squadrons
  from generating new sorties until resupply arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import math


class WarehouseCategory(str, Enum):
    """Broad supply categories tracked per warehouse."""
    AMMUNITION  = "ammunition"   # bombs, missiles, gun ammo (in "units")
    FUEL        = "fuel"         # JP-8 in tonnes
    SPARE_PARTS = "spare_parts"  # aircraft maintenance parts
    TROOPS      = "troops"       # infantry headcount
    VEHICLES    = "vehicles"     # ground vehicles (integer count)


# Spoilage rate per category per turn (0 = no decay, 0.05 = 5%/turn).
# Fuel evaporates slightly; troops don't spoil.
SPOILAGE_RATE: dict[WarehouseCategory, float] = {
    WarehouseCategory.AMMUNITION:  0.00,
    WarehouseCategory.FUEL:        0.02,
    WarehouseCategory.SPARE_PARTS: 0.00,
    WarehouseCategory.TROOPS:      0.00,
    WarehouseCategory.VEHICLES:    0.00,
}

# Hard capacity ceilings per category for a standard airbase.
# FARPs and road bases use smaller caps (see LogisticsManager).
DEFAULT_CAPACITY: dict[WarehouseCategory, float] = {
    WarehouseCategory.AMMUNITION:  5000.0,
    WarehouseCategory.FUEL:        2000.0,
    WarehouseCategory.SPARE_PARTS: 500.0,
    WarehouseCategory.TROOPS:      1000.0,
    WarehouseCategory.VEHICLES:    200.0,
}


@dataclass
class WarehouseItem:
    """
    A single line-item in the warehouse.

    quantity:  Current stock level (fractional for fuel/ammo).
    capacity:  Maximum this warehouse can hold of this category.
    reserved:  Amount set aside for planned missions this turn.
               Cannot be consumed until the mission resolves.
    """
    category: WarehouseCategory
    quantity: float = 0.0
    capacity: float = field(default=0.0)
    reserved: float = 0.0

    def __post_init__(self) -> None:
        if self.capacity == 0.0:
            self.capacity = DEFAULT_CAPACITY[self.category]

    @property
    def available(self) -> float:
        """Stock that can still be drawn (not reserved, not over capacity)."""
        return max(0.0, self.quantity - self.reserved)

    def add(self, amount: float) -> float:
        """
        Add stock. Returns how much was actually accepted (capped by capacity).
        Surplus is returned to the caller (e.g. to redistribute elsewhere).
        """
        headroom = self.capacity - self.quantity
        accepted = min(amount, max(0.0, headroom))
        self.quantity += accepted
        return accepted

    def consume(self, amount: float, ignore_reserve: bool = False) -> float:
        """
        Draw stock. Returns actual amount consumed (may be less if short).
        Reduces reserved by the same amount when ignore_reserve=False.
        """
        draw_from = self.quantity if ignore_reserve else self.available
        consumed = min(amount, max(0.0, draw_from))
        self.quantity -= consumed
        if not ignore_reserve:
            self.reserved = max(0.0, self.reserved - consumed)
        return consumed

    def reserve(self, amount: float) -> float:
        """Mark stock as reserved for a planned mission. Returns reserved amount."""
        can_reserve = min(amount, self.available)
        self.reserved += can_reserve
        return can_reserve

    def release_reserve(self, amount: float) -> None:
        """Release a reservation (mission cancelled or completed)."""
        self.reserved = max(0.0, self.reserved - amount)

    def apply_spoilage(self) -> float:
        """Apply per-turn decay. Returns amount lost."""
        rate = SPOILAGE_RATE[self.category]
        lost = self.quantity * rate
        self.quantity = max(0.0, self.quantity - lost)
        return lost

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "quantity": round(self.quantity, 2),
            "capacity": self.capacity,
            "reserved": round(self.reserved, 2),
        }

    @classmethod
    def from_dict(cls, data: dict) -> WarehouseItem:
        return cls(
            category=WarehouseCategory(data["category"]),
            quantity=data["quantity"],
            capacity=data.get("capacity", 0.0),
            reserved=data.get("reserved", 0.0),
        )


class Warehouse:
    """
    Full supply inventory for one ControlPoint.

    Usage example:
        wh = Warehouse(cp_id=5, cp_name="Batumi")
        wh.add(WarehouseCategory.FUEL, 800)
        wh.consume(WarehouseCategory.FUEL, 120)
        snapshot = wh.to_dict()          # save to campaign JSON
        wh2 = Warehouse.from_dict(snapshot)  # restore next session
    """

    def __init__(
        self,
        cp_id: int,
        cp_name: str,
        coalition: str = "blue",
        capacity_multiplier: float = 1.0,
    ) -> None:
        self.cp_id = cp_id
        self.cp_name = cp_name
        self.coalition = coalition
        # One WarehouseItem per category
        self.stock: dict[WarehouseCategory, WarehouseItem] = {
            cat: WarehouseItem(
                category=cat,
                capacity=DEFAULT_CAPACITY[cat] * capacity_multiplier,
            )
            for cat in WarehouseCategory
        }

    # ------------------------------------------------------------------
    # Core inventory operations
    # ------------------------------------------------------------------
    def add(self, category: WarehouseCategory, amount: float) -> float:
        """Add supply. Returns surplus that didn't fit."""
        accepted = self.stock[category].add(amount)
        return amount - accepted

    def consume(
        self,
        category: WarehouseCategory,
        amount: float,
        ignore_reserve: bool = False,
    ) -> float:
        """Draw supply. Returns how much was actually consumed."""
        return self.stock[category].consume(amount, ignore_reserve)

    def reserve(self, category: WarehouseCategory, amount: float) -> float:
        return self.stock[category].reserve(amount)

    def release_reserve(self, category: WarehouseCategory, amount: float) -> None:
        self.stock[category].release_reserve(amount)

    def quantity(self, category: WarehouseCategory) -> float:
        return self.stock[category].quantity

    def available(self, category: WarehouseCategory) -> float:
        return self.stock[category].available

    def is_critical(self, category: WarehouseCategory, threshold: float = 0.15) -> bool:
        """True when stock is below threshold % of capacity."""
        item = self.stock[category]
        if item.capacity == 0:
            return False
        return (item.quantity / item.capacity) < threshold

    # ------------------------------------------------------------------
    # Turn rollover
    # ------------------------------------------------------------------
    def apply_spoilage(self) -> dict[WarehouseCategory, float]:
        """Call at end of turn. Returns losses per category."""
        return {cat: item.apply_spoilage() for cat, item in self.stock.items()}

    def rollover(self, previous_snapshot: dict) -> None:
        """
        Import inventory from a previous turn's snapshot.

        This is the core 'warehouse carries over to next round' feature.
        Stock is preserved; reservations are cleared (they expire each turn).
        Spoilage is re-applied after import.
        """
        for cat_str, item_data in previous_snapshot.get("stock", {}).items():
            cat = WarehouseCategory(cat_str)
            item = WarehouseItem.from_dict(item_data)
            item.reserved = 0.0  # reservations don't carry over
            self.stock[cat] = item
        self.apply_spoilage()

    # ------------------------------------------------------------------
    # Import / Export between warehouses (supply chain transfers)
    # ------------------------------------------------------------------
    def export_to(
        self,
        destination: "Warehouse",
        category: WarehouseCategory,
        amount: float,
    ) -> float:
        """
        Transfer supply from this warehouse to another.
        Returns how much was actually transferred.
        Only available stock (not reserved) can be exported.
        """
        can_send = min(amount, self.available(category))
        consumed = self.consume(category, can_send)
        surplus = destination.add(category, consumed)
        # If destination was full, put surplus back
        if surplus > 0:
            self.add(category, surplus)
            consumed -= surplus
        return consumed

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "cp_id":     self.cp_id,
            "cp_name":   self.cp_name,
            "coalition": self.coalition,
            "stock": {
                cat.value: item.to_dict()
                for cat, item in self.stock.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Warehouse":
        wh = cls(
            cp_id=data["cp_id"],
            cp_name=data["cp_name"],
            coalition=data.get("coalition", "blue"),
        )
        for cat_str, item_data in data.get("stock", {}).items():
            cat = WarehouseCategory(cat_str)
            wh.stock[cat] = WarehouseItem.from_dict(item_data)
        return wh

    def summary(self) -> str:
        lines = [f"Warehouse — {self.cp_name} ({self.coalition})"]
        for cat, item in self.stock.items():
            pct = int(100 * item.quantity / item.capacity) if item.capacity else 0
            lines.append(
                f"  {cat.value:12s}  {item.quantity:7.1f} / {item.capacity:.0f}"
                f"  ({pct:3d}%)  reserved={item.reserved:.1f}"
            )
        return "\n".join(lines)
