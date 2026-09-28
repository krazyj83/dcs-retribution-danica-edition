"""Line chart of a base's warehouse stock, turn by turn.

One line per stock category (fuel, ammunition, supplies, troops), one point
per turn from game/logistics/history.py plus a last point for the stock as it
is now. Hovering the chart shows the numbers of the nearest turn.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from game.logistics.history import HistoryPoint

#: (field on HistoryPoint, label, colour)
SERIES = (
    ("fuel", "Fuel", "#3498db"),
    ("ammunition", "Ammunition", "#e67e22"),
    ("supplies", "Supplies", "#27ae60"),
    ("troops", "Troops", "#9b59b6"),
)

GRID = QColor(128, 128, 128, 70)
TEXT = QColor(160, 170, 180)


class QStockHistoryChart(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.points: List[HistoryPoint] = []
        #: Index of the "now" point (drawn hollow), or None.
        self.now_index: Optional[int] = None
        self.capacity = 1000.0
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

    def set_points(
        self,
        history: Sequence[HistoryPoint],
        now: Optional[HistoryPoint],
        capacity: float = 1000.0,
    ) -> None:
        self.points = list(history)
        self.now_index = None
        if now is not None:
            self.points.append(now)
            self.now_index = len(self.points) - 1
        self.capacity = capacity
        self.update()

    # ── Geometry ───────────────────────────────────────────────────────

    def _plot_rect(self) -> QRectF:
        return QRectF(40, 10, max(10, self.width() - 50), max(10, self.height() - 48))

    def _y_max(self) -> float:
        top = max(
            [self.capacity] + [getattr(p, f) for p in self.points for f, _, _ in SERIES]
        )
        return max(1.0, top)

    def _x(self, i: int, rect: QRectF) -> float:
        n = len(self.points)
        if n <= 1:
            return rect.center().x()
        return rect.left() + rect.width() * i / (n - 1)

    def _y(self, value: float, rect: QRectF) -> float:
        return rect.bottom() - rect.height() * value / self._y_max()

    # ── Painting ───────────────────────────────────────────────────────

    def paintEvent(self, event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot_rect()
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        painter.setFont(small)

        if not self.points:
            painter.setPen(TEXT)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No history yet: a point is recorded every turn when the "
                "mission is generated.",
            )
            return

        # Horizontal grid at 0, 25, 50, 75, 100% of the axis.
        top = self._y_max()
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = rect.bottom() - rect.height() * frac
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(TEXT)
            painter.drawText(
                QRectF(0, y - 8, rect.left() - 4, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{top * frac:.0f}",
            )

        # Turn labels (at most ~10 so they don't overlap).
        step = max(1, len(self.points) // 10)
        for i, p in enumerate(self.points):
            if i % step and i != len(self.points) - 1:
                continue
            label = "now" if i == self.now_index else str(p.turn)
            x = self._x(i, rect)
            painter.drawText(
                QRectF(x - 20, rect.bottom() + 2, 40, 14),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )

        for field, _, color in SERIES:
            pen = QPen(QColor(color), 2)
            path = QPainterPath()
            for i, p in enumerate(self.points):
                pt = QPointF(self._x(i, rect), self._y(getattr(p, field), rect))
                if i == 0:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            for i, p in enumerate(self.points):
                pt = QPointF(self._x(i, rect), self._y(getattr(p, field), rect))
                painter.setBrush(
                    Qt.BrushStyle.NoBrush if i == self.now_index else QColor(color)
                )
                painter.drawEllipse(pt, 3, 3)

        # Legend under the turn labels.
        x = rect.left()
        y = rect.bottom() + 20
        for _, label, color in SERIES:
            painter.setPen(QPen(QColor(color), 3))
            painter.drawLine(QPointF(x, y + 7), QPointF(x + 14, y + 7))
            painter.setPen(TEXT)
            painter.drawText(QRectF(x + 18, y, 90, 14), label)
            x += 18 + painter.fontMetrics().horizontalAdvance(label) + 16

    # ── Hover ──────────────────────────────────────────────────────────

    def nearest_index(self, x: float) -> Optional[int]:
        if not self.points:
            return None
        rect = self._plot_rect()
        return min(range(len(self.points)), key=lambda i: abs(self._x(i, rect) - x))

    def describe(self, i: int) -> str:
        p = self.points[i]
        title = "Now" if i == self.now_index else f"Turn {p.turn}"
        lines = [f"<b>{title}</b>"]
        prev = self.points[i - 1] if i > 0 else None
        for field, label, color in SERIES:
            value = getattr(p, field)
            change = ""
            if prev is not None:
                delta = value - getattr(prev, field)
                if abs(delta) >= 0.5:
                    change = f" ({delta:+.0f})"
            lines.append(
                f"<span style='color:{color}'>■</span> {label}: {value:.0f}{change}"
            )
        lines.append(f"Weapons in store: {p.weapons}")
        if p.fuel_used > 0:
            lines.append(f"Sortie fuel last mission: {p.fuel_used:.0f}")
        return "<br>".join(lines)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        i = self.nearest_index(event.position().x())
        if i is not None:
            QToolTip.showText(event.globalPosition().toPoint(), self.describe(i), self)
        super().mouseMoveEvent(event)
