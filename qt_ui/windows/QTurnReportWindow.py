"""Turn report window: what happened in a turn, on one page.

Data from game/logistics/turn_report.py. Opened from the toolbar ("Turn
report") and from the debrief window.
"""

from __future__ import annotations

from html import escape
from typing import Any, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

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

        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close)

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
        if not self.reports:
            self.view.setHtml(
                "<p>No turn reports yet: a report is made when a mission's "
                "results come in.</p>"
            )
            return
        self.view.setHtml(report_html(self.reports[max(0, index)]))
