"""How full a stock is: one set of thresholds for every screen.

Used by the Base Inventory bars, the map's supply rings, the turn report and
the REDFOR intel estimate, so a base reads the same everywhere:

    empty      at or below EMPTY_LEVEL
    critical   below CRITICAL_LEVEL
    low        below LOW_LEVEL (the resupply threshold)
    ok         everything else
"""

from __future__ import annotations

from typing import Tuple

EMPTY_LEVEL = 0.0
CRITICAL_LEVEL = 0.20
LOW_LEVEL = 0.40

COLORS = {
    "empty": "#e74c3c",
    "critical": "#e74c3c",
    "low": "#f39c12",
    "ok": "#27ae60",
}


def level(quantity: float, capacity: float) -> float:
    """Fraction 0..1 of the capacity."""
    if capacity <= 0:
        return 0.0
    return max(0.0, min(1.0, quantity / capacity))


def level_status(fraction: float) -> str:
    """ "empty", "critical", "low" or "ok"."""
    if fraction <= EMPTY_LEVEL:
        return "empty"
    if fraction < CRITICAL_LEVEL:
        return "critical"
    if fraction < LOW_LEVEL:
        return "low"
    return "ok"


def estimate(fraction: float) -> Tuple[str, str]:
    """(text, colour) of a level rounded to 10%, as an intel estimate."""
    status = level_status(fraction)
    if status == "empty":
        return "Exhausted", COLORS[status]
    label = {"critical": "Critical", "low": "Low", "ok": "Good"}[status]
    return f"{label} (~{int(round(fraction * 10)) * 10}%)", COLORS[status]
