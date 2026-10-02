"""Campaign-wide logistics numbers for the Logistics window's Campaign tab.

Two kinds of data:

- Stock over time: the per-base history (logistics/history.py) added up over
  the BLUEFOR bases, one point per turn.
- Activity per turn: what each mission cost. LogisticsManager.on_state_processed
  measures BLUEFOR totals just before and after each step (sortie fuel,
  weapons fired, depot and SAM damage, transfer settlement) and keeps the
  differences here, so no step has to report numbers of its own.

    turn   fuel used   weapons used   stock lost   delivered   lost
    3      412         26             150          2           0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, TypeVar

if TYPE_CHECKING:
    from game.logistics import LogisticsManager
    from game.logistics.history import HistoryPoint

T = TypeVar("T")

#: Turns of activity kept (same as the stock history).
MAX_TURNS = 200


@dataclass
class TurnStats:
    """What one turn's mission cost BLUEFOR."""

    turn: int
    #: Warehouse fuel used by sorties.
    fuel_used: float = 0.0
    #: Weapons taken from the weapon stores (fired, carried or lost).
    weapons_used: int = 0
    #: Fuel, ammunition and supplies lost to destroyed depots and SAM sites.
    stock_lost: float = 0.0
    transfers_delivered: int = 0
    transfers_lost: int = 0


@dataclass
class _Totals:
    fuel: float = 0.0
    stock: float = 0.0  # fuel + ammunition + supplies
    weapons: int = 0
    finished: Dict[str, str] = field(default_factory=dict)  # transfer -> status


def _blue_totals(logistics: LogisticsManager) -> _Totals:
    from game.logistics import WarehouseCategory

    totals = _Totals()
    blue_ids = set()
    for wh in logistics.warehouses_for_coalition("blue"):
        blue_ids.add(wh.cp_id)
        fuel = wh.stock[WarehouseCategory.FUEL].quantity
        totals.fuel += fuel
        totals.stock += (
            fuel
            + wh.stock[WarehouseCategory.AMMUNITION].quantity
            + wh.stock[WarehouseCategory.SUPPLIES].quantity
        )
    for inv in logistics._weapon_inventories.values():
        if inv.cp_id in blue_ids:
            totals.weapons += sum(int(i.quantity) for i in inv.items.values())
    for tid, t in logistics._transfers.items():
        totals.finished[tid] = t.status.value
    return totals


class StatsRecorder:
    """Measures the steps of one turn's results processing.

    recorder = StatsRecorder(logistics, turn)
    log = recorder.measure("fuel", lambda: use_fuel_for_sorties(game))
    recorder.start("transfers")
    ...  # inline code
    recorder.stop("transfers")
    recorder.save()
    """

    def __init__(self, logistics: LogisticsManager, turn: int) -> None:
        self.logistics = logistics
        self.stats = TurnStats(turn=turn)
        self._before: Dict[str, _Totals] = {}

    def measure(self, step: str, run: Callable[[], T]) -> T:
        """Run one step and add what it changed to the turn's numbers."""
        self.start(step)
        result = run()
        self.stop(step)
        return result

    def start(self, step: str) -> None:
        """Before a step that isn't a single call (see stop)."""
        self._before[step] = _blue_totals(self.logistics)

    def stop(self, step: str) -> None:
        before = self._before.pop(step, None)
        if before is None:
            return
        after = _blue_totals(self.logistics)
        if step == "fuel":
            self.stats.fuel_used += max(0.0, before.fuel - after.fuel)
        elif step == "weapons":
            self.stats.weapons_used += max(0, before.weapons - after.weapons)
        elif step == "damage":
            self.stats.stock_lost += max(0.0, before.stock - after.stock)
        elif step == "transfers":
            for tid, status in after.finished.items():
                if before.finished.get(tid) == status:
                    continue
                if status == "delivered":
                    self.stats.transfers_delivered += 1
                elif status == "failed":
                    self.stats.transfers_lost += 1

    def save(self) -> None:
        stats = self.logistics._turn_stats
        stats[self.stats.turn] = self.stats
        for turn in sorted(stats)[:-MAX_TURNS]:
            del stats[turn]


def turn_stats(logistics: Any) -> List[TurnStats]:
    """Recorded turns, oldest first."""
    return [logistics._turn_stats[t] for t in sorted(logistics._turn_stats)]


def blue_stock_history(logistics: Any) -> List[HistoryPoint]:
    """Stock of all BLUEFOR bases added up, one point per recorded turn.

    Bases count with the side they are on now: a base lost to REDFOR drops out
    of the earlier turns too.
    """
    from game.logistics.history import history_for

    by_turn: Dict[int, List[HistoryPoint]] = {}
    for wh in logistics.warehouses_for_coalition("blue"):
        for point in history_for(logistics, wh.cp_id):
            by_turn.setdefault(point.turn, []).append(point)
    return [_sum_points(turn, by_turn[turn]) for turn in sorted(by_turn)]


def blue_stock_now(logistics: Any, turn: int) -> Optional[HistoryPoint]:
    """The BLUEFOR stock as it is now, as one point."""
    from game.logistics.history import snapshot

    points = [
        snapshot(logistics, wh, turn)
        for wh in logistics.warehouses_for_coalition("blue")
    ]
    return _sum_points(turn, points) if points else None


def blue_capacity(logistics: Any) -> float:
    """Largest total capacity of one category, for the chart's scale."""
    from game.logistics import WarehouseCategory

    best = 0.0
    for category in WarehouseCategory:
        total = sum(
            wh.stock[category].capacity
            for wh in logistics.warehouses_for_coalition("blue")
        )
        best = max(best, total)
    return best or 1000.0


def _sum_points(turn: int, points: List[HistoryPoint]) -> HistoryPoint:
    from game.logistics.history import HistoryPoint

    return HistoryPoint(
        turn=turn,
        fuel=sum(p.fuel for p in points),
        ammunition=sum(p.ammunition for p in points),
        supplies=sum(p.supplies for p in points),
        troops=sum(p.troops for p in points),
        weapons=sum(p.weapons for p in points),
        fuel_used=sum(p.fuel_used for p in points),
    )
