"""
game/logistics/__init__.py  — ADD THESE METHODS to the existing StockItem dataclass
=====================================================================================
Your __init__.py already has:

    @dataclass
    class StockItem:
        quantity: float = 0.0
        capacity: float = 1000.0

Add the four properties/methods below directly inside that class, after the
two existing field declarations. They give the LogisticPlanner a clean way
to query supply levels and the debrief_hook a clean way to apply changes —
without duplicating the fields that already exist.

CONCEPT — @property vs regular method:
    @property makes a method callable without parentheses: item.level
    instead of item.level(). Use it for derived values that feel like
    attributes (read-only computed values). Use regular methods for
    actions that change state (apply_delivery, apply_consumption).
"""

# ── PASTE INSIDE class StockItem, after `capacity: float = 1000.0` ───────────

    @property
    def level(self) -> float:
        """
        Supply level as a fraction 0.0–1.0.
        0.0 = completely empty, 1.0 = at full capacity.
        Used by LogisticPlanner to decide if resupply is needed.
        """
        if self.capacity <= 0:
            return 0.0
        return min(1.0, self.quantity / self.capacity)

    @property
    def needs_resupply(self) -> bool:
        """
        True when supplies are below 40% of capacity.
        LogisticPlanner checks this each turn to decide whether to
        auto-generate a logistic flight to this base.
        Tune the threshold (0.40) to taste.
        """
        return self.level < 0.40

    def apply_delivery(self, amount: float) -> None:
        """
        Add amount to stock, clamped to capacity.
        Called by debrief_hook after a successful logistic flight.
        """
        self.quantity = min(self.capacity, self.quantity + amount)

    def apply_consumption(self, amount: float) -> None:
        """
        Subtract amount from stock, clamped to zero.
        Called each turn by LogisticPlanner.apply_turn_consumption()
        to simulate ongoing usage by stationed units and aircraft.
        """
        self.quantity = max(0.0, self.quantity - amount)

# ── END of additions ──────────────────────────────────────────────────────────
#
# Nothing else in __init__.py needs to change.
# The LogisticsManager, Warehouse, WeaponInventory, DropZone classes are
# all used as-is by the new logistic flight system.
#
# VERIFICATION — after adding, run:
#   python -c "from game.logistics import StockItem; s = StockItem(quantity=300, capacity=1000); print(s.level, s.needs_resupply)"
# Expected output: 0.3 True
