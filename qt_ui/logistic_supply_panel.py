"""
qt_ui/logistic_supply_panel.py  — NEW FILE

Supply status panel for the base info side panel.

Shows fuel and ammo levels for the selected control point and provides
a button to manually plan a logistic resupply flight.

To integrate, add to the control point info panel (QBaseMenu2.py or similar):

    from qt_ui.logistic_supply_panel import LogisticSupplyPanel

    if hasattr(game, "logistics") and game.logistics:
        wh = game.logistics.get_warehouse(cp.id)
        if wh is not None:
            self.tabs.addTab(
                LogisticSupplyPanel(cp, wh, game),
                "Supply"
            )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from game.logistics import WarehouseCategory

if TYPE_CHECKING:
    from game.game import Game
    from game.logistics import Warehouse
    from game.theater.controlpoint import ControlPoint


class SupplyBar(QWidget):
    """
    One supply-level indicator row:    Label  [████████░░]  42%

    Colors automatically based on level vs threshold:
      green  ≥ threshold
      orange between 50% and 100% of threshold
      red    below 50% of threshold
    """

    THRESHOLD = 0.40   # matches StockItem.needs_resupply

    def __init__(self, label: str, level: float, parent=None) -> None:
        super().__init__(parent)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)

        lbl = QLabel(label)
        lbl.setFixedWidth(70)
        row.addWidget(lbl)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(level * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(14)
        bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {self._color(level)}; }}"
        )
        row.addWidget(bar)

        pct = QLabel(f"{int(level * 100)}%")
        pct.setFixedWidth(36)
        pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(pct)

    def _color(self, level: float) -> str:
        if level >= self.THRESHOLD:
            return "#4CAF50"                     # green — adequate
        elif level >= self.THRESHOLD * 0.5:
            return "#FF9800"                     # orange — getting low
        else:
            return "#F44336"                     # red — critical


class LogisticSupplyPanel(QWidget):
    """
    Panel displayed in the base info tab strip showing supply levels
    and providing a manual resupply flight planning button.

    Args:
        cp:   The ControlPoint being inspected.
        wh:   Its Warehouse from LogisticsManager.
        game: The Game object (used to open package dialog).
    """

    def __init__(self, cp: ControlPoint, wh: Warehouse, game: Game, parent=None) -> None:
        super().__init__(parent)
        self.cp   = cp
        self.wh   = wh
        self.game = game

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Title ─────────────────────────────────────────────────────────────
        root.addWidget(QLabel(f"<b>Supply — {cp.name}</b>"))

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        root.addWidget(divider)

        # ── Supply bars ───────────────────────────────────────────────────────
        fuel_item = wh.stock.get(WarehouseCategory.FUEL)
        ammo_item = wh.stock.get(WarehouseCategory.AMMUNITION)
        supp_item = wh.stock.get(WarehouseCategory.SUPPLIES)

        root.addWidget(SupplyBar("Fuel",      fuel_item.level if fuel_item else 0.0))
        root.addWidget(SupplyBar("Ammo",      ammo_item.level if ammo_item else 0.0))
        root.addWidget(SupplyBar("Supplies",  supp_item.level if supp_item else 0.0))

        # ── Status text ───────────────────────────────────────────────────────
        status_lines = []
        if fuel_item and fuel_item.needs_resupply:
            status_lines.append(f"⚠ Fuel critical ({int(fuel_item.level * 100)}%)")
        if ammo_item and ammo_item.needs_resupply:
            status_lines.append(f"⚠ Ammo critical ({int(ammo_item.level * 100)}%)")
        if not status_lines:
            status_lines = ["✓ Supplies adequate"]

        status_lbl = QLabel("\n".join(status_lines))
        status_lbl.setWordWrap(True)
        root.addWidget(status_lbl)

        # ── Resupply button ───────────────────────────────────────────────────
        needs_resupply = (
            (fuel_item is not None and fuel_item.needs_resupply) or
            (ammo_item is not None and ammo_item.needs_resupply)
        )

        self.resupply_btn = QPushButton("Plan Resupply Flight")
        self.resupply_btn.setEnabled(needs_resupply)
        self.resupply_btn.setToolTip(
            "Open the package editor to manually plan a logistic "
            "resupply flight to this base."
        )
        self.resupply_btn.clicked.connect(self._on_resupply_clicked)
        root.addWidget(self.resupply_btn)

        root.addStretch()

    def _on_resupply_clicked(self) -> None:
        """
        Opens the package editor pre-configured for a LOGISTIC flight
        targeting this control point.

        Replace the placeholder below with the real PackageDialog call once
        you have located it. Search for:
            grep -rn "PackageDialog\|NewPackageDialog\|package.*dialog" qt_ui/
        """
        from PyQt5.QtWidgets import QMessageBox
        from game.ato.flighttype import FlightType

        # ── Placeholder — replace with real dialog call ────────────────────
        # Example pattern (adjust class name to match your codebase):
        #
        # from qt_ui.windows.mission.package.QPackageDialog import QPackageDialog
        # dialog = QPackageDialog(
        #     game=self.game,
        #     package=None,
        #     flight_type=FlightType.LOGISTIC,
        #     target_cp=self.cp,
        # )
        # dialog.exec_()

        QMessageBox.information(
            self,
            "Logistic Resupply",
            f"Plan a logistic flight to {self.cp.name}.\n\n"
            "Replace this placeholder with the real PackageDialog call.\n"
            "Run: grep -rn 'PackageDialog' qt_ui/ to find it.",
        )
