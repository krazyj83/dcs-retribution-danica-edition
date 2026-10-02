"""The "Copy for Discord" turn summary (game/logistics/discord_summary.py,
qt_ui/windows/QTurnReportWindow.py) and the Campaign tab's chart picture."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from game.logistics import LogisticsManager
from game.logistics.campaign_stats import TurnStats
from game.logistics.discord_summary import (
    DISCORD_LIMIT,
    discord_messages,
    split_for_discord,
    stats_for_turn,
)
from game.logistics.turn_report import TurnReport


def _report() -> TurnReport:
    report = TurnReport(turn=5, date="12 Jun 1985 14:00")
    report.losses = {
        "blue": {"Aircraft": 1},
        "red": {"Aircraft": 5, "Ground objects": 3},
    }
    report.add("events", ["Kobuleti captured by BLUEFOR"])
    report.add("supply", ["Senaki: fuel LOW (31%)"])
    return report


def test_summary_has_title_losses_activity_and_sections() -> None:
    stats = TurnStats(turn=5, fuel_used=412, weapons_used=26, transfers_delivered=2)
    (text,) = discord_messages(_report(), "Operation Danica", stats)

    assert text.startswith("**Operation Danica – Turn 5**  (12 Jun 1985 14:00)")
    assert "```\nLosses           Own  Enemy\n" in text
    assert "Aircraft           1      5" in text
    assert "Ground objects     0      3" in text
    assert "**Logistics:** 412 fuel used · 26 weapons used · 2 deliveries" in text
    assert "**Captures and convoys**\n- Kobuleti captured by BLUEFOR" in text
    assert "**Your bases short of supply**\n- Senaki: fuel LOW (31%)" in text
    # Sections follow the report's display order.
    assert text.index("Captures") < text.index("short of supply")


def test_quiet_turn() -> None:
    (text,) = discord_messages(TurnReport(turn=2, date=""))
    assert text == "**Turn 2**\n\nNo losses on either side."


def test_report_text_cannot_become_discord_formatting() -> None:
    report = TurnReport(turn=1, date="")
    report.add("events", ["F-14 *Tomcat* lost_at sea | `x`"])
    (text,) = discord_messages(report)
    assert r"F-14 \*Tomcat\* lost\_at sea \| \`x\`" in text


def test_long_report_is_split_into_whole_blocks() -> None:
    report = _report()
    report.add("fuel", [f"Base {i}: 4 sortie(s) used 60 fuel" for i in range(80)])
    messages = discord_messages(report, "Op", None)

    assert len(messages) > 1
    assert all(len(m) <= DISCORD_LIMIT for m in messages)
    assert messages[0].startswith("**Op – Turn 5**")
    # The losses table is never cut in half.
    assert messages[0].count("```") == 2
    # Every line made it, once.
    joined = "\n".join(messages)
    assert all(joined.count(f"Base {i}: ") == 1 for i in range(80))


def test_split_packs_blocks_and_cuts_oversized_ones() -> None:
    assert split_for_discord(["a" * 5, "b" * 5], limit=12) == ["aaaaa\n\nbbbbb"]
    assert split_for_discord(["a" * 5, "b" * 5], limit=11) == ["aaaaa", "bbbbb"]
    assert split_for_discord(["x\n" * 3 + "y" * 25], limit=10) == [
        "x\nx\nx",
        "y" * 10,
        "y" * 10,
        "y" * 5,
    ]


def test_stats_for_turn() -> None:
    lm = LogisticsManager()
    lm._turn_stats[3] = TurnStats(turn=3, fuel_used=1)
    assert stats_for_turn(lm, 3).fuel_used == 1
    assert stats_for_turn(lm, 4) is None


# --- the windows ---------------------------------------------------------------


def _app() -> Any:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_copy_for_discord_copies_each_part_in_turn() -> None:
    app = _app()
    from qt_ui.windows.QTurnReportWindow import QTurnReportWindow

    lm = LogisticsManager()
    report = _report()
    report.add("fuel", [f"Base {i}: 4 sortie(s) used 60 fuel" for i in range(80)])
    lm._turn_reports[5] = report
    window = QTurnReportWindow(SimpleNamespace(logistics=lm, campaign_name="Op"))

    expected = window._messages()
    assert len(expected) > 1
    copied = []
    for n in range(1, len(expected) + 1):
        window.discord.click()
        copied.append(app.clipboard().text())
        assert f"Part {n} of {len(expected)} copied" in window.copied.text()
        if n < len(expected):
            assert window.discord.text() == f"Copy part {n + 1} of {len(expected)}"
    assert copied == expected
    assert copied[0].startswith("**Op – Turn 5**")
    assert window.discord.text() == "Copy for Discord"  # ready to start again


def test_copy_for_discord_is_off_without_reports() -> None:
    _app()
    from qt_ui.windows.QTurnReportWindow import QTurnReportWindow

    window = QTurnReportWindow(SimpleNamespace(logistics=LogisticsManager()))
    assert not window.discord.isEnabled()


def test_campaign_tab_takes_a_picture_of_its_charts() -> None:
    app = _app()
    from qt_ui.windows.logistics.QCampaignTab import CampaignTab

    tab = CampaignTab(LogisticsManager(), SimpleNamespace(turn=3))  # type: ignore[arg-type]
    tab.resize(900, 700)
    tab.show()
    image = tab.charts_image()
    assert image.width() > 0 and image.height() > 0

    tab._copy_image()
    assert not app.clipboard().pixmap().isNull()
