"""The turn report: one page with what happened in a turn's mission.

A report is started when the mission results are processed
(LogisticsManager.on_state_processed) and filled as the rest of the turn is
settled: losses of both sides, captures and convoys, supply flights, fuel,
weapons used, depot damage, recon, REDFOR resupply, repairs and grounded
packages, and bases whose supply is low. The last MAX_REPORTS turns are kept
with the campaign; the Turn report window (toolbar and debrief window) shows
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from game import Game

MAX_REPORTS = 30

#: Report sections in display order: key -> title.
SECTIONS = {
    "events": "Captures and convoys",
    "flights": "Supply flights",
    "fuel": "Fuel",
    "weapons": "Weapons used",
    "damage": "Depot and SAM damage",
    "recon": "Recon",
    "enemy": "Enemy logistics",
    "supply": "Your bases short of supply",
}

#: SideLossCounts field -> label, in display order.
LOSS_LABELS = {
    "aircraft": "Aircraft",
    "front_line": "Front line units",
    "motorpool": "Motorpool units",
    "convoy": "Convoy units",
    "player_drawn_convoy": "Player convoy units",
    "cargo_ships": "Shipping cargo",
    "airlift_cargo": "Airlift cargo",
    "ground_objects": "Ground objects",
    "scenery": "Scenery objects",
    "editor_units": "Mission editor units",
    "bases_captured": "Bases captured",
    "runways_destroyed": "Runways destroyed",
}


@dataclass
class TurnReport:
    turn: int
    date: str
    #: "blue"/"red" -> loss label -> count.
    losses: Dict[str, Dict[str, int]] = field(default_factory=dict)
    sections: Dict[str, List[str]] = field(default_factory=dict)

    def add(self, section: str, lines: List[str]) -> None:
        if not lines:
            return
        existing = self.sections.setdefault(section, [])
        for line in lines:
            if line not in existing:
                existing.append(line)


def _reports(logistics: Any) -> Dict[int, TurnReport]:
    reports = getattr(logistics, "_turn_reports", None)
    if reports is None:
        reports = {}
        logistics._turn_reports = reports
    return reports


def all_reports(logistics: Any) -> List[TurnReport]:
    """Newest first."""
    return sorted(_reports(logistics).values(), key=lambda r: -r.turn)


def latest(logistics: Any) -> Optional[TurnReport]:
    reports = all_reports(logistics)
    return reports[0] if reports else None


def add_to_latest(logistics: Any, section: str, lines: List[str]) -> None:
    report = latest(logistics)
    if report is not None:
        report.add(section, lines)


def _loss_table(counts: Any) -> Dict[str, int]:
    names = {f.name for f in fields(counts)}
    return {
        label: int(getattr(counts, name))
        for name, label in LOSS_LABELS.items()
        if name in names
    }


def start_report(game: Game, debriefing: Any, pending: List[str]) -> TurnReport:
    """A new report for the mission just flown (replacing one for the turn)."""
    from game.theater.player import Player

    try:
        when = f"{game.conditions.start_time:%d %b %Y %H:%M}"
    except Exception:
        when = ""
    report = TurnReport(turn=game.turn, date=when)
    try:
        report.losses = {
            "blue": _loss_table(debriefing.loss_counts(Player.BLUE)),
            "red": _loss_table(debriefing.loss_counts(Player.RED)),
        }
    except Exception:
        report.losses = {}
    report.add("events", list(pending))
    reports = _reports(game.logistics)
    reports[game.turn] = report
    for turn in sorted(reports)[:-MAX_REPORTS]:
        del reports[turn]
    return report


def supply_warnings(game: Game) -> List[str]:
    from game.logistics.supply_status import supply_status

    lines = []
    for row in supply_status(game):
        if row.side != "blue" or row.status == "ok":
            continue
        lines.append(f"{row.cp.name}: {row.status.upper()} ({', '.join(row.reasons)})")
    return lines
