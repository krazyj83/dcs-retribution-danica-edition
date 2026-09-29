"""Turn reports (game/logistics/turn_report.py, qt_ui/windows/QTurnReportWindow.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from game.debriefing import SideLossCounts
from game.logistics import LogisticsManager
from game.logistics.turn_report import (
    MAX_REPORTS,
    add_to_latest,
    all_reports,
    start_report,
)
from game.theater.player import Player


def _counts(aircraft: int, editor: int = 0) -> SideLossCounts:
    return SideLossCounts(
        aircraft=aircraft,
        front_line=0,
        motorpool=0,
        convoy=0,
        player_drawn_convoy=0,
        cargo_ships=0,
        airlift_cargo=0,
        ground_objects=3,
        scenery=0,
        bases_captured=0,
        bases_lost=0,
        runways_destroyed=0,
        editor_units=editor,
    )


def _game(turn: int = 4) -> Any:
    return SimpleNamespace(
        logistics=LogisticsManager(),
        turn=turn,
        conditions=SimpleNamespace(start_time=None),
    )


DEBRIEF = SimpleNamespace(
    loss_counts=lambda p: _counts(1) if p is Player.BLUE else _counts(5, editor=2)
)


def test_report_collects_losses_and_lines() -> None:
    game = _game()
    report = start_report(game, DEBRIEF, ["Kobuleti captured by BLUEFOR: fuel kept"])
    report.add("fuel", ["Larnaca: 4 sortie(s) used 65 fuel"])
    add_to_latest(game.logistics, "enemy", ["REDFOR Maykop: 2 package(s) grounded"])
    add_to_latest(game.logistics, "enemy", ["REDFOR Maykop: 2 package(s) grounded"])

    (stored,) = all_reports(game.logistics)
    assert stored.losses["blue"]["Aircraft"] == 1
    assert stored.losses["red"]["Mission editor units"] == 2
    assert stored.sections["events"] == ["Kobuleti captured by BLUEFOR: fuel kept"]
    assert stored.sections["enemy"] == ["REDFOR Maykop: 2 package(s) grounded"]


def test_only_the_last_reports_are_kept_newest_first() -> None:
    game = _game()
    for turn in range(1, MAX_REPORTS + 6):
        game.turn = turn
        start_report(game, DEBRIEF, [])
    reports = all_reports(game.logistics)
    assert len(reports) == MAX_REPORTS
    assert reports[0].turn == MAX_REPORTS + 5


def test_report_html() -> None:
    from qt_ui.windows.QTurnReportWindow import report_html

    game = _game()
    report = start_report(game, DEBRIEF, [])
    report.add("weapons", ["Larnaca: OUT OF AIM-120C"])
    html = report_html(report)
    assert "<h2>Turn 4</h2>" in html
    assert "Ground objects" in html and "Weapons used" in html
    assert "#e74c3c'>Larnaca: OUT OF AIM-120C" in html
    assert "Supply flights" not in html  # empty sections are left out
