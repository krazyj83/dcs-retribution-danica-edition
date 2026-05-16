"""
qt_ui/windows/logistics/QLogisticsWindow.py

Logistics & Supply Chain window for DCS Retribution.
Opens as a popup dialog from the main toolbar (alongside Settings, Stats, Notes).

Three tabs:
  1. Drop Zones  — create/edit/delete troop and cargo drop zones
  2. Warehouses  — view stock levels, transfer stock between bases
  3. Transfers   — schedule, monitor, and cancel logistics deliveries

Concept — how Qt dialogs work in this codebase:
  Every popup window (QSettingsWindow, QStatsWindow, QNotesWindow) extends
  QDialog. The main window holds a reference as self.dialog and calls .show()
  which displays it as a non-blocking window the player can leave open while
  interacting with the map. We follow exactly the same pattern here.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QLineEdit,
    QComboBox,
    QDoubleSpinBox,
    QTextEdit,
    QGroupBox,
    QMessageBox,
    QFormLayout,
    QDialogButtonBox,
    QCheckBox,
    QWidget,
)

from game import Game
from game.logistics import (
    DropZone,
    DropZoneType,
    Warehouse,
    WarehouseCategory,
    LogisticsManager,
    LogisticsTransfer,
    TransferStatus,
)


# ======================================================================
# Colour helpers
# ======================================================================

STOCK_CRITICAL_COLOR = QColor("#c0392b")  # red   < 15%
STOCK_LOW_COLOR = QColor("#e67e22")       # amber  15-40%
STOCK_OK_COLOR = QColor("#27ae60")        # green  > 40%

STATUS_COLORS = {
    TransferStatus.PLANNED:   QColor("#3498db"),
    TransferStatus.IN_FLIGHT: QColor("#f39c12"),
    TransferStatus.DELIVERED: QColor("#27ae60"),
    TransferStatus.FAILED:    QColor("#c0392b"),
}


def stock_color(quantity: float, capacity: float) -> QColor:
    if capacity == 0:
        return STOCK_OK_COLOR
    pct = quantity / capacity
    if pct < 0.15:
        return STOCK_CRITICAL_COLOR
    if pct < 0.40:
        return STOCK_LOW_COLOR
    return STOCK_OK_COLOR


# ======================================================================
# Drop Zone creation / edit dialog
# ======================================================================

class DropZoneDialog(QDialog):
    """
    Modal dialog for creating or editing a DropZone.

    Concept — QDialog vs QWidget:
      QDialog blocks interaction with its parent until closed (if exec_() is
      used) or floats independently (if show() is used). We use exec_() here
      so the player must finish editing a drop zone before returning to the
      main logistics window. This prevents partial state issues.
    """

    def __init__(
        self,
        cp_id: int,
        cp_name: str,
        coalition: str,
        parent: Optional[QWidget] = None,
        existing: Optional[DropZone] = None,
    ) -> None:
        super().__init__(parent)
        self.cp_id = cp_id
        self.cp_name = cp_name
        self.coalition = coalition
        self.existing = existing
        self.setWindowTitle(
            f"{'Edit' if existing else 'New'} Drop Zone — {cp_name}"
        )
        self.setMinimumWidth(420)
        self._build_ui()
        if existing:
            self._populate(existing)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. LZ ALPHA")
        form.addRow("Zone name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Troop drop zone", DropZoneType.TROOP)
        self.type_combo.addItem("Cargo drop zone", DropZoneType.CARGO)
        form.addRow("Type:", self.type_combo)

        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(6)
        self.lat_spin.setSingleStep(0.001)
        form.addRow("Latitude:", self.lat_spin)

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(6)
        self.lon_spin.setSingleStep(0.001)
        form.addRow("Longitude:", self.lon_spin)

        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(100.0, 5000.0)
        self.radius_spin.setSingleStep(100.0)
        self.radius_spin.setValue(500.0)
        self.radius_spin.setSuffix(" m")
        form.addRow("Radius:", self.radius_spin)

        self.active_check = QCheckBox("Active (include in next mission)")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("Optional notes...")
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, dz: DropZone) -> None:
        self.name_edit.setText(dz.name)
        idx = self.type_combo.findData(dz.dz_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.lat_spin.setValue(dz.lat)
        self.lon_spin.setValue(dz.lon)
        self.radius_spin.setValue(dz.radius_m)
        self.active_check.setChecked(dz.active)
        self.notes_edit.setPlainText(dz.notes)

    def _on_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Zone name cannot be empty.")
            return
        self.accept()

    def get_drop_zone(self) -> DropZone:
        """Build and return a DropZone from the current dialog state."""
        kwargs = dict(
            name=self.name_edit.text().strip().upper(),
            dz_type=self.type_combo.currentData(),
            lat=self.lat_spin.value(),
            lon=self.lon_spin.value(),
            radius_m=self.radius_spin.value(),
            cp_id=self.cp_id,
            coalition=self.coalition,
            active=self.active_check.isChecked(),
            notes=self.notes_edit.toPlainText(),
        )
        if self.existing:
            kwargs["dz_id"] = self.existing.dz_id
        return DropZone(**kwargs)


# ======================================================================
# Tab 1 — Drop Zones
# ======================================================================

class DropZonesTab(QWidget):
    """
    Lists all drop zones for the player coalition.
    Allows creating, editing, and deleting zones.

    Each zone the player creates will appear in the next generated .miz
    file as a DCS trigger zone, named using the DropZone.trigger_zone_name
    convention so that Lua scripts (MOOSE CTLD etc.) can find them.
    """

    dropZoneAdded   = Signal(object)  # DropZone
    dropZoneRemoved = Signal(str)     # dz_id
    dropZoneUpdated = Signal(object)  # DropZone

    def __init__(self, logistics: LogisticsManager, coalition: str) -> None:
        super().__init__()
        self.logistics = logistics
        self.coalition = coalition
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar row
        toolbar = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Drop Zone")
        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Type", "Latitude", "Longitude", "Radius (m)", "Active", "Notes"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        info = QLabel(
            "Drop zones appear as trigger zones in the generated .miz file. "
            "Lua scripts (MOOSE CTLD) use their names to identify landing and drop targets."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(info)

    def refresh(self) -> None:
        dzs = self.logistics.active_drop_zones(self.coalition)
        self.table.setRowCount(len(dzs))
        for row, dz in enumerate(dzs):
            self.table.setItem(row, 0, QTableWidgetItem(dz.name))
            type_item = QTableWidgetItem(dz.dz_type.value.capitalize())
            type_item.setForeground(
                QColor("#e67e22")
                if dz.dz_type == DropZoneType.TROOP
                else QColor("#3498db")
            )
            self.table.setItem(row, 1, type_item)
            self.table.setItem(row, 2, QTableWidgetItem(f"{dz.lat:.6f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{dz.lon:.6f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{dz.radius_m:.0f}"))
            active_item = QTableWidgetItem("✓" if dz.active else "✗")
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, active_item)
            self.table.setItem(row, 6, QTableWidgetItem(dz.notes))
            # Store dz_id as hidden data on the name cell for retrieval
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, dz.dz_id)

    def _selected_dz_id(self) -> Optional[str]:
        if not self.table.selectedItems():
            return None
        return self.table.item(
            self.table.currentRow(), 0
        ).data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        has = bool(self.table.selectedItems())
        self.edit_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)

    def _on_add(self) -> None:
        # In a full implementation the cp_id/cp_name would come from
        # a base-selector combo populated from game.theater.control_points.
        # Using defaults here so the dialog works without extra wiring.
        dlg = DropZoneDialog(
            cp_id=0,
            cp_name="Select a base",
            coalition=self.coalition,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dz = dlg.get_drop_zone()
            self.logistics.add_drop_zone(dz)
            self.dropZoneAdded.emit(dz)
            self.refresh()

    def _on_edit(self) -> None:
        dz_id = self._selected_dz_id()
        if not dz_id:
            return
        existing = self.logistics.get_drop_zone(dz_id)
        if not existing:
            return
        dlg = DropZoneDialog(
            cp_id=existing.cp_id,
            cp_name="Selected Base",
            coalition=self.coalition,
            parent=self,
            existing=existing,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.get_drop_zone()
            self.logistics._drop_zones[dz_id] = updated
            self.dropZoneUpdated.emit(updated)
            self.refresh()

    def _on_delete(self) -> None:
        dz_id = self._selected_dz_id()
        if not dz_id:
            return
        dz = self.logistics.get_drop_zone(dz_id)
        reply = QMessageBox.question(
            self,
            "Delete Drop Zone",
            f"Delete drop zone '{dz.name}'?\n"
            "Any planned transfers to this zone will be cancelled.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logistics.remove_drop_zone(dz_id)
            self.dropZoneRemoved.emit(dz_id)
            self.refresh()


# ======================================================================
# Tab 2 — Warehouses
# ======================================================================

class WarehouseTab(QWidget):
    """
    Shows stock levels for all player-coalition bases and allows
    direct stock transfers between them (instant, no aircraft needed).

    Concept — why two types of transfer?
      - Direct export (this tab): instant rebalancing between bases,
        used before a mission to set up supply lines. No aircraft needed.
      - Scheduled transfer (Transfers tab): requires a helicopter or
        transport aircraft, happens during the mission, can fail if the
        aircraft is shot down.
    """

    def __init__(self, logistics: LogisticsManager, coalition: str) -> None:
        super().__init__()
        self.logistics = logistics
        self.coalition = coalition
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Stock table
        self.table = QTableWidget()
        cats = list(WarehouseCategory)
        self.table.setColumnCount(1 + len(cats))
        self.table.setHorizontalHeaderLabels(
            ["Base"] + [c.value.replace("_", " ").title() for c in cats]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        # Direct export panel
        export_group = QGroupBox("Direct Stock Transfer (instant, no aircraft)")
        exp_layout = QFormLayout()

        self.from_combo = QComboBox()
        self.to_combo = QComboBox()
        self.cat_combo = QComboBox()
        for cat in WarehouseCategory:
            self.cat_combo.addItem(cat.value.replace("_", " ").title(), cat)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.0, 99999.0)
        self.amount_spin.setSingleStep(50.0)
        self.amount_spin.setDecimals(0)

        self.export_btn = QPushButton("Transfer Now")
        self.export_btn.clicked.connect(self._on_export)

        exp_layout.addRow("From base:", self.from_combo)
        exp_layout.addRow("To base:",   self.to_combo)
        exp_layout.addRow("Category:",  self.cat_combo)
        exp_layout.addRow("Amount:",    self.amount_spin)
        exp_layout.addRow("",           self.export_btn)
        export_group.setLayout(exp_layout)
        layout.addWidget(export_group)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        warehouses = self.logistics.warehouses_for_coalition(self.coalition)
        cats = list(WarehouseCategory)
        self.table.setRowCount(len(warehouses))

        self.from_combo.clear()
        self.to_combo.clear()

        for row, wh in enumerate(warehouses):
            self.table.setItem(row, 0, QTableWidgetItem(wh.cp_name))
            self.from_combo.addItem(wh.cp_name, wh.cp_id)
            self.to_combo.addItem(wh.cp_name, wh.cp_id)

            for col, cat in enumerate(cats, start=1):
                item_data = wh.stock[cat]
                pct = (
                    int(100 * item_data.quantity / item_data.capacity)
                    if item_data.capacity
                    else 0
                )
                text = (
                    f"{item_data.quantity:.0f} / {item_data.capacity:.0f} ({pct}%)"
                )
                cell = QTableWidgetItem(text)
                cell.setForeground(
                    stock_color(item_data.quantity, item_data.capacity)
                )
                self.table.setItem(row, col, cell)

    def _on_export(self) -> None:
        from_cp_id = self.from_combo.currentData()
        to_cp_id   = self.to_combo.currentData()
        category   = self.cat_combo.currentData()
        amount     = self.amount_spin.value()

        if from_cp_id == to_cp_id:
            self.status_label.setText("⚠ Source and destination must differ.")
            return
        if amount <= 0:
            self.status_label.setText("⚠ Amount must be greater than zero.")
            return

        src_wh = self.logistics.get_warehouse(from_cp_id)
        dst_wh = self.logistics.get_warehouse(to_cp_id)
        if src_wh is None or dst_wh is None:
            self.status_label.setText("⚠ Warehouse not found.")
            return

        transferred = src_wh.export_to(dst_wh, category, amount)
        self.status_label.setText(
            f"✓ Transferred {transferred:.0f} {category.value} "
            f"from {src_wh.cp_name} → {dst_wh.cp_name}"
        )
        self.refresh()


# ======================================================================
# Tab 3 — Transfers
# ======================================================================

class TransfersTab(QWidget):
    """
    Schedule logistics transfers — helicopter or transport missions that
    carry stock from a source base to a drop zone at a destination base.

    Unlike the direct export on the Warehouses tab, these transfers:
      - Reserve stock at source immediately
      - Spawn an actual aircraft in the next generated mission
      - Can fail if the aircraft is destroyed before reaching the drop zone
      - Are reported back via state.json after the mission ends
    """

    transferScheduled = Signal(object)  # LogisticsTransfer

    def __init__(
        self,
        logistics: LogisticsManager,
        coalition: str,
        current_turn: int = 0,
    ) -> None:
        super().__init__()
        self.logistics = logistics
        self.coalition = coalition
        self.current_turn = current_turn
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Schedule new transfer
        sched_group = QGroupBox("Schedule New Transfer (requires aircraft + drop zone)")
        sched_layout = QFormLayout()

        self.src_combo  = QComboBox()
        self.dst_combo  = QComboBox()
        self.dz_combo   = QComboBox()
        self.tcat_combo = QComboBox()
        for cat in WarehouseCategory:
            self.tcat_combo.addItem(cat.value.replace("_", " ").title(), cat)

        self.tamt_spin = QDoubleSpinBox()
        self.tamt_spin.setRange(1.0, 9999.0)
        self.tamt_spin.setSingleStep(50.0)
        self.tamt_spin.setDecimals(0)
        self.tamt_spin.setValue(200.0)

        self.aircraft_edit = QLineEdit("UH-1H")
        self.tnotes_edit   = QLineEdit()
        self.tnotes_edit.setPlaceholderText("Optional notes...")

        self.dst_combo.currentIndexChanged.connect(self._on_dst_changed)

        self.schedule_btn = QPushButton("Schedule Transfer")
        self.schedule_btn.clicked.connect(self._on_schedule)

        sched_layout.addRow("From base:",     self.src_combo)
        sched_layout.addRow("To base:",       self.dst_combo)
        sched_layout.addRow("Drop zone:",     self.dz_combo)
        sched_layout.addRow("Category:",      self.tcat_combo)
        sched_layout.addRow("Quantity:",      self.tamt_spin)
        sched_layout.addRow("Aircraft type:", self.aircraft_edit)
        sched_layout.addRow("Notes:",         self.tnotes_edit)
        sched_layout.addRow("",               self.schedule_btn)
        sched_group.setLayout(sched_layout)
        layout.addWidget(sched_group)

        # Transfer log
        layout.addWidget(QLabel("Transfer log:"))
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "From", "To", "Category",
            "Planned", "Delivered", "Status", "Turn",
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self.cancel_btn = QPushButton("Cancel Selected Transfer")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn)

        self.table.itemSelectionChanged.connect(self._on_sel_changed)
        self.sched_status = QLabel("")
        layout.addWidget(self.sched_status)

    def refresh(self) -> None:
        warehouses = self.logistics.warehouses_for_coalition(self.coalition)
        for combo in (self.src_combo, self.dst_combo):
            combo.clear()
            for wh in warehouses:
                combo.addItem(wh.cp_name, wh.cp_id)

        self._on_dst_changed()

        all_transfers = list(self.logistics._transfers.values())
        self.table.setRowCount(len(all_transfers))
        for row, t in enumerate(all_transfers):
            src_wh = self.logistics.get_warehouse(t.source_cp_id)
            dst_wh = self.logistics.get_warehouse(t.dest_cp_id)
            self.table.setItem(
                row, 0, QTableWidgetItem(t.transfer_id[:8])
            )
            self.table.setItem(
                row, 1,
                QTableWidgetItem(src_wh.cp_name if src_wh else str(t.source_cp_id)),
            )
            self.table.setItem(
                row, 2,
                QTableWidgetItem(dst_wh.cp_name if dst_wh else str(t.dest_cp_id)),
            )
            self.table.setItem(row, 3, QTableWidgetItem(t.category.value))
            self.table.setItem(row, 4, QTableWidgetItem(f"{t.quantity:.0f}"))
            self.table.setItem(
                row, 5,
                QTableWidgetItem(f"{t.delivered:.0f}" if t.delivered else "—"),
            )
            status_item = QTableWidgetItem(t.status.value.capitalize())
            status_item.setForeground(
                STATUS_COLORS.get(t.status, QColor("white"))
            )
            self.table.setItem(row, 6, status_item)
            self.table.setItem(row, 7, QTableWidgetItem(str(t.turn_planned)))
            self.table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, t.transfer_id
            )

    def _on_dst_changed(self) -> None:
        dst_cp_id = self.dst_combo.currentData()
        self.dz_combo.clear()
        if dst_cp_id is not None:
            for dz in self.logistics.drop_zones_for_cp(dst_cp_id):
                if dz.active:
                    self.dz_combo.addItem(
                        f"{dz.name} ({dz.dz_type.value})", dz.dz_id
                    )

    def _on_schedule(self) -> None:
        src_cp_id = self.src_combo.currentData()
        dst_cp_id = self.dst_combo.currentData()
        dz_id     = self.dz_combo.currentData()
        category  = self.tcat_combo.currentData()
        quantity  = self.tamt_spin.value()
        aircraft  = self.aircraft_edit.text().strip() or "UH-1H"
        notes     = self.tnotes_edit.text().strip()

        if src_cp_id == dst_cp_id:
            self.sched_status.setText("⚠ Source and destination must differ.")
            return
        if not dz_id:
            self.sched_status.setText(
                "⚠ No active drop zone at destination. Add one in the Drop Zones tab."
            )
            return

        transfer = self.logistics.schedule_transfer(
            source_cp_id=src_cp_id,
            dest_cp_id=dst_cp_id,
            dz_id=dz_id,
            category=category,
            quantity=quantity,
            aircraft_type=aircraft,
            turn=self.current_turn,
            notes=notes,
        )
        if transfer is None:
            self.sched_status.setText(
                "⚠ Insufficient available stock at source warehouse."
            )
        else:
            self.sched_status.setText(
                f"✓ Transfer {transfer.transfer_id[:8]} scheduled."
            )
            self.transferScheduled.emit(transfer)
            self.refresh()

    def _on_sel_changed(self) -> None:
        if not self.table.selectedItems():
            self.cancel_btn.setEnabled(False)
            return
        tid = self.table.item(
            self.table.currentRow(), 0
        ).data(Qt.ItemDataRole.UserRole)
        t = self.logistics._transfers.get(tid)
        self.cancel_btn.setEnabled(
            t is not None and t.status == TransferStatus.PLANNED
        )

    def _on_cancel(self) -> None:
        if not self.table.selectedItems():
            return
        tid = self.table.item(
            self.table.currentRow(), 0
        ).data(Qt.ItemDataRole.UserRole)
        if self.logistics.cancel_transfer(tid):
            self.sched_status.setText(f"Transfer {tid[:8]} cancelled.")
            self.refresh()


# ======================================================================
# Main logistics window
# ======================================================================

class QLogisticsWindow(QDialog):
    """
    Top-level Logistics & Supply Chain window.

    Opened from the main toolbar via QLiberationWindow.showLogisticsDialog().
    Follows the same pattern as QSettingsWindow, QStatsWindow, QNotesWindow:
      self.dialog = QLogisticsWindow(self.game)
      self.dialog.show()

    If no campaign is loaded (game is None), shows a placeholder message
    rather than crashing — matches the behaviour of the other windows.
    """

    def __init__(self, game: Optional[Game], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.game = game
        self.setWindowTitle("Logistics & Supply Chain")
        self.setMinimumSize(920, 640)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header = QLabel("Logistics & Supply Chain")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        # Guard: no campaign loaded
        if self.game is None or not hasattr(self.game, "logistics"):
            placeholder = QLabel(
                "No campaign is currently loaded.\n"
                "Start or load a campaign to manage logistics."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: grey; font-size: 13px;")
            layout.addWidget(placeholder)
            return

        logistics: LogisticsManager = self.game.logistics
        coalition = "blue"
        turn = getattr(self.game, "turn", 0)

        # Three-tab layout
        tabs = QTabWidget()

        self.dz_tab = DropZonesTab(logistics, coalition)
        tabs.addTab(self.dz_tab, "Drop Zones")

        self.wh_tab = WarehouseTab(logistics, coalition)
        tabs.addTab(self.wh_tab, "Warehouses")

        self.tr_tab = TransfersTab(logistics, coalition, current_turn=turn)
        tabs.addTab(self.tr_tab, "Transfers")

        layout.addWidget(tabs)

        # Close button at the bottom
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def refresh(self) -> None:
        """Call after each turn to update all sub-tabs with fresh data."""
        if hasattr(self, "dz_tab"):
            self.dz_tab.refresh()
        if hasattr(self, "wh_tab"):
            self.wh_tab.refresh()
        if hasattr(self, "tr_tab"):
            self.tr_tab.refresh()
