"""Base window tab: what the base holds.

Top: warehouse stock (fuel, ammunition, supplies, troops) as level bars,
and a chart of the stock turn by turn.
Left: weapon stores by category, with search and a low/empty filter.
Right: supply flights to and from the base, naval munitions crates, and a
button to the Logistics window, where stock is changed.

Read-only: the data comes from game.logistics.base_inventory.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from game import Game
from game.logistics.base_inventory import BaseInventory, base_inventory
from game.theater import ControlPoint
from qt_ui.models import GameModel
from qt_ui.windows.basemenu.inventory.QStockHistoryChart import QStockHistoryChart

from game.logistics.levels import COLORS, level_status

GOOD = COLORS["ok"]
LOW = COLORS["low"]
EMPTY = COLORS["empty"]

#: What each bar counts (hover text). Ammunition is bulk munitions; aircraft
#: weapons are the separate weapon stores listed below the bars.
_BAR_TIPS = {
    "fuel": "Fuel for aircraft and vehicles. Sorties from this base use it.",
    "ammunition": (
        "Bulk munitions: shipped as crates to rearm ships, spent on SAM repairs "
        "and lost in depot strikes.\nAircraft weapons are the weapon stores "
        "below."
    ),
    "supplies": "General supplies: spent on SAM repairs, lost in depot strikes.",
    "troops": "Troops moved by logistics transfers.",
}


def _status_text(fraction: float) -> str:
    status = level_status(fraction)
    if status == "empty":
        return "Empty"
    if status == "critical":
        return "Critical"
    if status == "low":
        return "Needs resupply"
    return f"{fraction:.0%}"


class QBaseInventory(QFrame):
    def __init__(self, cp: ControlPoint, game_model: GameModel) -> None:
        super().__init__()
        self.cp = cp
        self.game_model = game_model
        self.inventory: Optional[BaseInventory] = None
        self._bars: dict[str, tuple[QProgressBar, QLabel]] = {}
        self._build_ui()
        self.refresh()

    # ── Layout ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title)

        stock_box = QGroupBox("Warehouse stock")
        grid = QGridLayout(stock_box)
        from game.logistics import WarehouseCategory

        for row, cat in enumerate(WarehouseCategory):
            name = cat.value.capitalize()
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(True)
            status = QLabel()
            tip = _BAR_TIPS.get(cat.value, "")
            bar.setToolTip(tip)
            label = QLabel(name)
            label.setToolTip(tip)
            grid.addWidget(label, row, 0)
            grid.addWidget(bar, row, 1)
            grid.addWidget(status, row, 2)
            self._bars[cat.value] = (bar, status)
        grid.setColumnStretch(1, 1)
        # How long the fuel lasts at the last mission's rate.
        self.fuel_label = QLabel()
        self.fuel_label.setWordWrap(True)
        grid.addWidget(self.fuel_label, len(WarehouseCategory), 0, 1, 3)
        top = QHBoxLayout()
        top.addWidget(stock_box, 1)

        history_box = QGroupBox("Stock history (hover for numbers)")
        hl = QVBoxLayout(history_box)
        self.history_chart = QStockHistoryChart()
        hl.addWidget(self.history_chart)
        top.addWidget(history_box, 1)
        layout.addLayout(top)

        body = QHBoxLayout()

        weapons_box = QGroupBox("Weapon stores")
        wl = QVBoxLayout(weapons_box)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search weapons (e.g. AIM-120, GBU)")
        self.search.textChanged.connect(self._fill_weapons)
        filters.addWidget(self.search)
        self.only_low = QCheckBox("Only low / empty")
        self.only_low.toggled.connect(self._fill_weapons)
        filters.addWidget(self.only_low)
        wl.addLayout(filters)
        self.weapon_summary = QLabel()
        wl.addWidget(self.weapon_summary)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Weapon", "Qty", "Capacity"])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(False)
        wl.addWidget(self.tree)
        self.sync_button = QPushButton("Sync weapon stores from campaign")
        self.sync_button.setToolTip(
            "Adds the weapons this base's squadrons can carry. Stock already\n"
            "tracked keeps its quantity (same as Logistics > Inventory > Sync)."
        )
        self.sync_button.clicked.connect(self._on_sync)
        wl.addWidget(self.sync_button)
        body.addWidget(weapons_box, 7)

        side = QVBoxLayout()
        flights_box = QGroupBox("Supply flights")
        fl = QVBoxLayout(flights_box)
        self.flights_label = QLabel()
        self.flights_label.setWordWrap(True)
        self.flights_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        fl.addWidget(self.flights_label)
        side.addWidget(flights_box)

        naval_box = QGroupBox("Ship rearming")
        nl = QVBoxLayout(naval_box)
        self.naval_label = QLabel()
        self.naval_label.setWordWrap(True)
        nl.addWidget(self.naval_label)
        side.addWidget(naval_box)

        side.addStretch()
        open_logistics = QPushButton("Open Logistics window…")
        open_logistics.clicked.connect(self._open_logistics)
        side.addWidget(open_logistics)
        side_widget = QWidget()
        side_widget.setLayout(side)
        body.addWidget(side_widget, 3)

        layout.addLayout(body, 1)

    # ── Data ───────────────────────────────────────────────────────────

    @property
    def game(self) -> Game:
        game = self.game_model.game
        assert game is not None
        return game

    def showEvent(self, event: QShowEvent) -> None:
        # Stock can change in the Logistics window while this one is open.
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        self.inventory = base_inventory(self.game, self.cp)
        inv = self.inventory
        self.title.setText(
            f"{inv.base_name}{'  —  Main supply base' if inv.is_main_base else ''}"
        )

        for row in inv.stock:
            bar, status = self._bars[row.category.value]
            bar.setValue(int(row.level * 1000))
            bar.setFormat(f"{row.quantity:.0f} / {row.capacity:.0f}")
            color = COLORS[level_status(row.level)]
            bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {color}; }}"
                "QProgressBar { text-align: center; }"
            )
            status.setText(_status_text(row.level))
            status.setStyleSheet(f"color: {color};")

        self.fuel_label.setText(self._fuel_text(inv))
        self._fill_history()

        lines = []
        if inv.incoming:
            lines.append("<b>Incoming</b>")
            lines += [f"• {line}" for line in inv.incoming]
        if inv.outgoing:
            lines.append("<b>Outgoing</b>")
            lines += [f"• {line}" for line in inv.outgoing]
        self.flights_label.setText(
            "<br>".join(lines) if lines else "No supply flights planned."
        )
        self.naval_label.setText(
            f"{inv.naval_crates} naval munitions crate(s) available "
            "(one crate per 50 ammunition)."
        )
        self._fill_weapons()

    @staticmethod
    def _fuel_text(inv: BaseInventory) -> str:
        from game.logistics import WarehouseCategory

        if inv.unlimited_fuel:
            return (
                "Fuel: not tracked here (ships are supplied at sea, or the "
                "Unlimited warehouse fuel setting is on)."
            )
        fuel = next(r for r in inv.stock if r.category is WarehouseCategory.FUEL)
        if fuel.quantity <= 0:
            return (
                f"<span style='color:{EMPTY}'><b>Out of fuel.</b></span> "
                "Flights can still be planned; resupply this base."
            )
        if inv.fuel_turns_left is None:
            return "Fuel: no sorties from this base last mission."
        color = LOW if inv.fuel_turns_left < 3 else GOOD
        return (
            f"Fuel: last mission used {inv.fuel_used_last_mission:.0f}, "
            f"<span style='color:{color}'><b>about {inv.fuel_turns_left:.1f} "
            "turns left</b></span> at that rate."
        )

    def _fill_history(self) -> None:
        from game.logistics.history import HistoryPoint, history_for, snapshot

        logistics = self.game.logistics
        warehouse = logistics.get_warehouse(self.cp.id)
        if warehouse is None:
            self.history_chart.set_points([], None)
            return
        capacity = max(item.capacity for item in warehouse.stock.values())
        turn = getattr(self.game, "turn", 0)
        current: Optional[HistoryPoint] = snapshot(logistics, warehouse, turn)
        history = history_for(logistics, self.cp.id)
        # Leave out "now" when nothing changed since this turn's point.
        if history and history[-1] == current:
            current = None
        self.history_chart.set_points(history, current, capacity)

    def _fill_weapons(self) -> None:
        self.tree.clear()
        inv = self.inventory
        if inv is None or inv.weapons is None:
            self.weapon_summary.setText(
                "Weapon stores have not been synced for this base yet."
            )
            self.sync_button.setVisible(True)
            return
        self.sync_button.setVisible(False)

        types, empty, low = inv.weapon_totals
        self.weapon_summary.setText(
            f"{types} weapon types · "
            f"<span style='color:{EMPTY}'>{empty} empty</span> · "
            f"<span style='color:{LOW}'>{low} low</span>"
        )

        needle = self.search.text().strip().lower()
        only_low = self.only_low.isChecked()
        for category, rows in inv.weapons.items():
            shown = [
                r
                for r in rows
                if (not needle or needle in r.name.lower())
                and (not only_low or r.empty or r.low)
            ]
            if not shown:
                continue
            total = sum(r.quantity for r in shown)
            parent = QTreeWidgetItem([category, str(total), ""])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            for r in shown:
                child = QTreeWidgetItem([r.name, str(r.quantity), str(r.capacity)])
                if r.empty:
                    child.setForeground(1, QBrush(QColor(EMPTY)))
                elif r.low:
                    child.setForeground(1, QBrush(QColor(LOW)))
                if r.variants > 1:
                    child.setToolTip(
                        0,
                        f"{r.variants} variants (different racks or launchers), "
                        "counted together",
                    )
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
                child.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
                parent.addChild(child)
            parent.setExpanded(bool(needle) or only_low)

    # ── Actions ────────────────────────────────────────────────────────

    def _on_sync(self) -> None:
        self.game.logistics.sync_weapon_inventories(self.game)
        self.refresh()

    def _open_logistics(self) -> None:
        # Reuse the main window's Logistics window so only one is open.
        for widget in QApplication.topLevelWidgets():
            opener = getattr(widget, "showLogisticsDialog", None)
            if callable(opener):
                opener()
                return
        from qt_ui.windows.logistics.QLogisticsWindow import QLogisticsWindow

        self._logistics_window = QLogisticsWindow(self.game)
        self._logistics_window.show()
