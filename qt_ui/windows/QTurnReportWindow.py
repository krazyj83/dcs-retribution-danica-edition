"""Turn report window: what happened in a turn, on one page.

Data from game/logistics/turn_report.py. Opened from the toolbar ("Turn
report") and from the debrief window. "Copy for Discord" puts the shown turn
on the clipboard as Discord text (game/logistics/discord_summary.py); a long
report is copied in parts, one click per part.
"""

from __future__ import annotations

from html import escape
from typing import Any, List, Optional

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from game.logistics.discord_summary import discord_messages, stats_for_turn
from game.logistics.turn_report import (
    LOSS_LABELS,
    SECTIONS,
    TurnReport,
    all_reports,
)

BLUE = "#3498db"
RED = "#e74c3c"


def _line_html(line: str) -> str:
    text = escape(line)
    if "OUT OF" in line or "CRITICAL" in line or "lost" in line:
        return f"<span style='color:{RED}'>{text}</span>"
    if "LOW" in line or "grounded" in line:
        return f"<span style='color:#f39c12'>{text}</span>"
    return text


def report_html(report: TurnReport) -> str:
    """The report as HTML (kept separate from the window so it can be tested)."""
    parts = [f"<h2>Turn {report.turn}</h2>"]
    if report.date:
        parts.append(f"<p style='color:#95a5a6'>Mission of {escape(report.date)}</p>")

    blue = report.losses.get("blue", {})
    red = report.losses.get("red", {})
    rows = [
        (label, blue.get(label, 0), red.get(label, 0))
        for label in LOSS_LABELS.values()
        if blue.get(label, 0) or red.get(label, 0)
    ]
    parts.append("<h3>Losses</h3>")
    if rows:
        table = [
            "<table cellspacing='0' cellpadding='3'>",
            f"<tr><th align='left'></th><th style='color:{BLUE}'>OwnFor</th>"
            f"<th style='color:{RED}'>OpFor</th></tr>",
        ]
        for label, b, r in rows:
            table.append(
                f"<tr><td>{escape(label)}</td><td align='center'>{b}</td>"
                f"<td align='center'>{r}</td></tr>"
            )
        table.append("</table>")
        parts.append("".join(table))
    else:
        parts.append("<p>No losses on either side.</p>")

    for key, title in SECTIONS.items():
        lines = report.sections.get(key)
        if not lines:
            continue
        parts.append(f"<h3>{escape(title)}</h3><ul>")
        parts.extend(f"<li>{_line_html(line)}</li>" for line in lines)
        parts.append("</ul>")
    return "".join(parts)


class QTurnReportWindow(QDialog):
    def __init__(self, game: Any, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.game = game
        self.setWindowTitle("Turn report")
        self.resize(640, 720)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Turn:"))
        self.turns = QComboBox()
        self.turns.currentIndexChanged.connect(self._show)
        top.addWidget(self.turns, 1)
        layout.addLayout(top)

        self.view = QTextBrowser()
        layout.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        self.discord = QPushButton("Copy for Discord")
        self.discord.setToolTip(
            "Copy this turn as text to paste in Discord. A long report is "
            "copied in parts: click again for the next part."
        )
        self.discord.clicked.connect(self._copy_for_discord)
        buttons.addWidget(self.discord)
        self.copied = QLabel("")
        self.copied.setStyleSheet("color:#95a5a6")
        buttons.addWidget(self.copied, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._parts: List[str] = []
        self._next_part = 0

        self.refresh()

    def refresh(self) -> None:
        self.reports = all_reports(self.game.logistics)
        self.turns.blockSignals(True)
        self.turns.clear()
        for report in self.reports:
            label = f"Turn {report.turn}"
            if report.date:
                label += f"  ({report.date})"
            self.turns.addItem(label)
        self.turns.blockSignals(False)
        self._show(0)

    def _show(self, index: int) -> None:
        self._parts = []
        self._next_part = 0
        if hasattr(self, "discord"):
            self.discord.setText("Copy for Discord")
            self.discord.setEnabled(bool(self.reports))
            self.copied.setText("")
        if not self.reports:
            self.view.setHtml(
                "<p>No turn reports yet: a report is made when a mission's "
                "results come in.</p>"
            )
            return
        self.view.setHtml(report_html(self.reports[max(0, index)]))

    def _messages(self) -> List[str]:
        report = self.reports[max(0, self.turns.currentIndex())]
        return discord_messages(
            report,
            str(getattr(self.game, "campaign_name", "") or ""),
            stats_for_turn(self.game.logistics, report.turn),
        )

    def _copy_for_discord(self) -> None:
        if not self.reports:
            return
        if not self._parts or self._next_part >= len(self._parts):
            self._parts = self._messages()
            self._next_part = 0
        part = self._parts[self._next_part]
        QGuiApplication.clipboard().setText(part)
        self._next_part += 1
        total = len(self._parts)
        if total == 1:
            self.copied.setText("Copied - paste it in Discord.")
            return
        self.copied.setText(
            f"Part {self._next_part} of {total} copied - paste it, then copy "
            "the next part."
        )
        if self._next_part < total:
            self.discord.setText(f"Copy part {self._next_part + 1} of {total}")
        else:
            self.discord.setText("Copy for Discord")
