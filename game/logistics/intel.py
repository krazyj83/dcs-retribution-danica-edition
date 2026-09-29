"""What BLUEFOR knows about REDFOR base supplies: recon intel.

REDFOR's fuel, ammunition and supplies (logistics/redfor.py) are only known
from recon. After each mission, every enemy land base that a surviving
BLUEFOR flight had a planned waypoint within RECON_RADIUS of is "seen": its
stock at that moment is recorded as an intel report. Reports older than
STALE_AFTER_TURNS turns are no longer shown.

The report is shown on the map's "Base supply status" layer (dotted rings
around enemy bases, fading with age) and on the enemy base's Intel tab. A
flight that planned to fly near the base but was shot down entirely brings
nothing back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from game.logistics import LogisticsManager

logger = logging.getLogger(__name__)

RECON_RADIUS_M = 30_000.0
STALE_AFTER_TURNS = 4


@dataclass(frozen=True)
class IntelReport:
    turn: int
    fuel: float
    ammunition: float
    supplies: float
    #: Flight that brought it back (for the tooltip).
    source: str


def _reports(logistics: LogisticsManager) -> Dict[Any, IntelReport]:
    reports = getattr(logistics, "_red_intel", None)
    if reports is None:
        reports = {}
        logistics._red_intel = reports
    return reports


def _level(item: Any) -> float:
    return 0.0 if item.capacity <= 0 else item.quantity / item.capacity


def seen_bases(game: Any, debriefing: Any) -> Dict[Any, Tuple[Any, str]]:
    """REDFOR bases seen by a surviving BLUEFOR flight: cp.id -> (cp, flight)."""
    from game.logistics.redfor import is_red_land_base

    red_bases = [cp for cp in game.theater.controlpoints if is_red_land_base(cp)]
    seen: Dict[Any, Tuple[Any, str]] = {}
    for package in game.blue.ato.packages:
        for flight in package.flights:
            try:
                if debriefing.air_losses.surviving_flight_members(flight) <= 0:
                    continue
                points = [w.position for w in flight.flight_plan.waypoints]
            except Exception:
                continue
            for cp in red_bases:
                if cp.id in seen:
                    continue
                if any(
                    p.distance_to_point(cp.position) <= RECON_RADIUS_M for p in points
                ):
                    seen[cp.id] = (cp, str(flight))
    return seen


def record_recon(game: Any, debriefing: Any) -> List[str]:
    """After the mission: record what surviving flights saw. Log lines."""
    from game.logistics import WarehouseCategory
    from game.logistics.redfor import enabled

    if not enabled(game):
        return []
    logistics = game.logistics
    reports = _reports(logistics)
    log: List[str] = []
    for cp_id, (cp, source) in seen_bases(game, debriefing).items():
        warehouse = logistics.get_warehouse(cp_id)
        if warehouse is None:
            continue
        stock = warehouse.stock
        report = IntelReport(
            turn=game.turn,
            fuel=_level(stock[WarehouseCategory.FUEL]),
            ammunition=_level(stock[WarehouseCategory.AMMUNITION]),
            supplies=_level(stock[WarehouseCategory.SUPPLIES]),
            source=source,
        )
        reports[cp_id] = report
        log.append(
            f"Recon over {cp.name}: fuel {estimate(report.fuel)[0]}, "
            f"ammunition {estimate(report.ammunition)[0]}"
        )
    for line in log:
        logger.info(line)
    return log


def intel_for(game: Any, cp: Any) -> Optional[Tuple[IntelReport, int]]:
    """(report, age in turns) for an enemy base, or None: none or stale."""
    logistics = getattr(game, "logistics", None)
    if logistics is None or not cp.captured.is_red:
        return None
    report = _reports(logistics).get(cp.id)
    if report is None:
        return None
    age = max(0, getattr(game, "turn", 0) - report.turn)
    if age > STALE_AFTER_TURNS:
        return None
    return report, age


def forget(logistics: Any, cp_id: Any) -> None:
    """The base changed hands: what was known about it no longer applies."""
    _reports(logistics).pop(cp_id, None)


def estimate(level: float) -> Tuple[str, str]:
    """(text, colour) for a stock level, rounded like an intel estimate."""
    rounded = int(round(level * 10)) * 10
    if level <= 0.02:
        return "Exhausted", "#e74c3c"
    if level < 0.2:
        return f"Critical (~{rounded}%)", "#e74c3c"
    if level < 0.4:
        return f"Low (~{rounded}%)", "#f39c12"
    return f"Good (~{rounded}%)", "#27ae60"


def age_text(age: int) -> str:
    if age == 0:
        return "from this turn's recon"
    return f"recon {age} turn{'s' if age > 1 else ''} old"
