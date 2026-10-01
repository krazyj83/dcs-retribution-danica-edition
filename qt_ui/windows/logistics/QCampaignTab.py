"""Campaign tab of the Logistics window: BLUEFOR logistics across the campaign.

    ┌ Bases ──┐┌ Fuel ───┐┌ Weapons ┐┌ Transfers ┐   headline numbers
    └─────────┘└─────────┘└─────────┘└───────────┘
    Stock, all bases (line chart, one line per category)
    Fuel used │ Weapons used │ Stock lost          one small bar chart each,
                                                   per turn, own scale
    Bases now (table)                             double-click opens the base
    Per turn (table)                              the numbers behind the bars

Data from game/logistics/campaign_stats.py (per-turn activity and the stock
history added up) and game/logistics/supply_status.py (each base now).
Double-click a base to show it on the Warehouses tab.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from game import Game
from game.logistics import LogisticsManager
from game.logistics.campaign_stats import (
    TurnStats,
    blue_capacity,
    blue_stock_history,
    blue_stock_now,
    turn_stats,
)
from game.logistics.levels import COLORS
from qt_ui.windows.basemenu.inventory.QStockHistoryChart import QStockHistoryChart

GRID = QColor(128, 128, 128, 60)
TEXT = QColor(160, 170, 180)

#: (TurnStats field, chart title, colour). Fuel matches the stock chart's fuel
#: line; stock lost is neutral grey, as red is kept for the "critical" status.
ACTIVITY = (
    ("fuel_used", "Fuel used by sorties", "#3498db"),
    ("weapons_used", "Weapons used", "#9b59b6"),
    ("stock_lost", "Stock lost to strikes", "#7f8c8d"),
)


class QTurnBarChart(QWidget):
    """Bars of one number per turn, on its own scale; hover a bar for its value."""

    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.title = title
        self.color = QColor(color)
        self.values: List[Tuple[int, float]] = []
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

    def set_values(self, values: Sequence[Tuple[int, float]]) -> None:
        self.values = list(values)
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(36, 22, max(10, self.width() - 44), max(10, self.height() - 44))

    def _bars(self) -> List[Tuple[QRectF, int, float]]:
        plot = self._plot()
        if not self.values:
            return []
        top = max(v for _, v in self.values) or 1.0
        slot = plot.width() / len(self.values)
        width = max(2.0, min(18.0, slot - 2.0))  # 2px gap between bars
        bars = []
        for i, (turn, value) in enumerate(self.values):
            h = plot.height() * value / top
            x = plot.left() + i * slot + (slot - width) / 2
            bars.append((QRectF(x, plot.bottom() - h, width, h), turn, value))
        return bars

    def paintEvent(self, event: Any) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 0.9)
        p.setFont(font)

        p.setPen(TEXT)
        p.drawText(
            QRectF(0, 0, self.width(), 18), Qt.AlignmentFlag.AlignLeft, self.title
        )
        if not self.values:
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No missions recorded yet")
            return
        if not any(v > 0 for _, v in self.values):
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "None so far")
            return

        top = max(v for _, v in self.values)
        # Recessive grid: the baseline and the top value only.
        p.setPen(QPen(GRID, 1))
        p.drawLine(
            QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom())
        )
        p.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.right(), plot.top()))
        p.setPen(TEXT)
        p.drawText(
            QRectF(0, plot.top() - 8, 32, 16), Qt.AlignmentFlag.AlignRight, f"{top:.0f}"
        )
        p.drawText(
            QRectF(0, plot.bottom() - 8, 32, 16), Qt.AlignmentFlag.AlignRight, "0"
        )

        bars = self._bars()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        for rect, _, value in bars:
            if value <= 0:
                continue
            # Rounded at the data end, square on the baseline.
            radius = min(3.0, rect.width() / 2, rect.height())
            path = QPainterPath()
            path.moveTo(rect.left(), rect.bottom())
            path.lineTo(rect.left(), rect.top() + radius)
            path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
            path.lineTo(rect.right() - radius, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            p.drawPath(path)

        # Turn labels: first, last and a few between so they don't collide.
        p.setPen(TEXT)
        step = max(1, len(bars) // 6)
        for i, (rect, turn, _) in enumerate(bars):
            if i % step and i != len(bars) - 1:
                continue
            p.drawText(
                QRectF(rect.center().x() - 20, plot.bottom() + 3, 40, 14),
                Qt.AlignmentFlag.AlignHCenter,
                str(turn),
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        for rect, turn, value in self._bars():
            # Hit target is the whole column, not just the (maybe tiny) bar.
            column = QRectF(
                rect.left() - 2,
                self._plot().top(),
                rect.width() + 4,
                self._plot().height(),
            )
            if column.contains(pos):
                QToolTip.showText(
                    event.globalPosition().toPoint(), f"Turn {turn}: {value:.0f}", self
                )
                return
        QToolTip.hideText()


def _tile(title: str) -> Tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 6, 10, 6)
    caption = QLabel(title)
    caption.setStyleSheet("color: grey;")
    value = QLabel()
    font = QFont()
    font.setPointSize(15)
    font.setBold(True)
    value.setFont(font)
    detail = QLabel()
    detail.setStyleSheet("color: grey;")
    layout.addWidget(caption)
    layout.addWidget(value)
    layout.addWidget(detail)
    return frame, value, detail


def _change(now: float, before: Optional[float]) -> str:
    if before is None:
        return "no earlier turn"
    diff = now - before
    sign = "+" if diff >= 0 else "−"
    return f"{sign}{abs(diff):.0f} since last turn"


def _item(text: str, sort: Optional[float] = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if sort is not None:
        item.setData(Qt.ItemDataRole.UserRole, sort)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
    return item


def _percent(value: float, capacity: float) -> str:
    return f"{value:.0f} ({value / capacity:.0%})" if capacity > 0 else f"{value:.0f}"


class CampaignTab(QWidget):
    def __init__(
        self,
        logistics: LogisticsManager,
        game: Game,
        on_base: Optional[Callable[[Any], None]] = None,
    ) -> None:
        super().__init__()
        self.logistics = logistics
        self.game = game
        self.on_base = on_base
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        tiles = QHBoxLayout()
        frame, self.bases_value, self.bases_detail = _tile("Bases")
        tiles.addWidget(frame)
        frame, self.fuel_value, self.fuel_detail = _tile("Fuel in depots")
        tiles.addWidget(frame)
        frame, self.weapons_value, self.weapons_detail = _tile("Weapons in stores")
        tiles.addWidget(frame)
        frame, self.transfers_value, self.transfers_detail = _tile("Transfers")
        tiles.addWidget(frame)
        layout.addLayout(tiles)

        stock_box = QGroupBox("Stock, all BLUEFOR bases (hover for numbers)")
        stock_layout = QVBoxLayout(stock_box)
        self.stock_chart = QStockHistoryChart()
        self.stock_chart.setMinimumHeight(200)
        stock_layout.addWidget(self.stock_chart)
        layout.addWidget(stock_box)

        activity_box = QGroupBox("What each mission cost")
        activity = QHBoxLayout(activity_box)
        self.activity_charts = {}
        for key, title, color in ACTIVITY:
            chart = QTurnBarChart(title, color)
            self.activity_charts[key] = chart
            activity.addWidget(chart)
        layout.addWidget(activity_box)

        bases_box = QGroupBox("Bases now (double-click to open on Warehouses)")
        bl = QVBoxLayout(bases_box)
        self.bases_table = QTableWidget(0, 6)
        self.bases_table.setHorizontalHeaderLabels(
            ["Base", "Status", "Fuel", "Ammunition", "Turns of fuel", "Why"]
        )
        self._setup_table(self.bases_table)
        self.bases_table.cellDoubleClicked.connect(self._on_base_double_clicked)
        bl.addWidget(self.bases_table)
        layout.addWidget(bases_box)

        turns_box = QGroupBox("Per turn (newest first)")
        tl = QVBoxLayout(turns_box)
        self.turns_table = QTableWidget(0, 6)
        self.turns_table.setHorizontalHeaderLabels(
            [
                "Turn",
                "Fuel used",
                "Weapons used",
                "Stock lost to strikes",
                "Transfers delivered",
                "Transfers lost",
            ]
        )
        self._setup_table(self.turns_table)
        # Numbers only: share the width evenly.
        self.turns_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        tl.addWidget(self.turns_table)
        layout.addWidget(turns_box)

    @staticmethod
    def _setup_table(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(180)

    # ── Data ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        turn = int(getattr(self.game, "turn", 0))
        history = blue_stock_history(self.logistics)
        now = blue_stock_now(self.logistics, turn)
        stats = turn_stats(self.logistics)

        self.stock_chart.set_points(history, now, blue_capacity(self.logistics))
        for key, chart in self.activity_charts.items():
            chart.set_values([(s.turn, float(getattr(s, key))) for s in stats])

        self._fill_tiles(history, now, stats)
        self._fill_turns(stats)
        self._fill_bases()

    def _fill_tiles(
        self, history: Sequence[Any], now: Any, stats: List[TurnStats]
    ) -> None:
        # The last recorded point is this turn's; compare with the turn before.
        before = history[-2] if len(history) >= 2 else None
        if now is not None:
            self.fuel_value.setText(f"{now.fuel:.0f}")
            self.fuel_detail.setText(_change(now.fuel, before.fuel if before else None))
            self.weapons_value.setText(f"{now.weapons}")
            self.weapons_detail.setText(
                _change(now.weapons, before.weapons if before else None)
            )
        delivered = sum(s.transfers_delivered for s in stats)
        lost = sum(s.transfers_lost for s in stats)
        self.transfers_value.setText(f"{delivered} delivered")
        self.transfers_detail.setText(f"{lost} lost · since tracking began")

        counts = {"ok": 0, "low": 0, "critical": 0}
        for row in self._blue_rows():
            counts[row.status if row.status in counts else "ok"] += 1
        self.bases_value.setText(str(sum(counts.values())))
        self.bases_detail.setText(
            f"<span style='color:{COLORS['ok']}'>●</span> {counts['ok']} ok  "
            f"<span style='color:{COLORS['low']}'>●</span> {counts['low']} low  "
            f"<span style='color:{COLORS['critical']}'>●</span> "
            f"{counts['critical']} critical"
        )

    def _fill_turns(self, stats: List[TurnStats]) -> None:
        table = self.turns_table
        table.setSortingEnabled(False)
        table.setRowCount(len(stats))
        for row, s in enumerate(reversed(stats)):  # newest first
            values = [
                _item(str(s.turn), s.turn),
                _item(f"{s.fuel_used:.0f}", s.fuel_used),
                _item(str(s.weapons_used), s.weapons_used),
                _item(f"{s.stock_lost:.0f}", s.stock_lost),
                _item(str(s.transfers_delivered), s.transfers_delivered),
                _item(str(s.transfers_lost), s.transfers_lost),
            ]
            for col, item in enumerate(values):
                table.setItem(row, col, item)

    def _blue_rows(self) -> List[Any]:
        from game.logistics.supply_status import supply_status

        try:
            rows = supply_status(self.game)
        except Exception:
            return []
        return [r for r in rows if getattr(r, "side", "blue") != "red"]

    def _fill_bases(self) -> None:
        rows = sorted(
            self._blue_rows(),
            key=lambda r: ({"critical": 0, "low": 1}.get(r.status, 2), r.cp.name),
        )
        table = self.bases_table
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name = _item(r.cp.name)
            name.setData(Qt.ItemDataRole.UserRole, r.cp.id)
            status = _item(f"● {r.status.capitalize()}")
            status.setForeground(QColor(COLORS.get(r.status, COLORS["ok"])))
            turns = (
                "unlimited"
                if r.unlimited_fuel
                else (
                    f"{r.fuel_turns_left:.1f}" if r.fuel_turns_left is not None else "–"
                )
            )
            cells = [
                name,
                status,
                _item(_percent(r.fuel, r.fuel_capacity)),
                _item(_percent(r.ammunition, r.ammunition_capacity)),
                _item(turns),
                _item(", ".join(r.reasons)),
            ]
            for col, item in enumerate(cells):
                table.setItem(i, col, item)

    def _on_base_double_clicked(self, row: int, _column: int) -> None:
        item = self.bases_table.item(row, 0)
        if item is not None and self.on_base is not None:
            self.on_base(item.data(Qt.ItemDataRole.UserRole))
