"""
qt_ui/windows/logistics/QLogisticsWindow.py

Logistics & Supply Chain window for DCS Retribution.
Opens as a popup dialog from the main toolbar (alongside Settings, Stats, Notes).

Three tabs:
  1. Drop Zones  - create/edit/delete troop and cargo drop zones
  2. Warehouses  - view stock levels, transfer stock between bases,
                   export/import warehouse inventory via CSV
  3. Transfers   - schedule, monitor, and cancel logistics deliveries
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Tuple

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
    QFileDialog,
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
STOCK_LOW_COLOR      = QColor("#e67e22")  # amber  15-40%
STOCK_OK_COLOR       = QColor("#27ae60")  # green  > 40%

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


def get_blue_control_points(game: Game):
    """Return list of blue coalition control points."""
    try:
        return list(game.theater.player_points())
    except Exception:
        return []


def cp_latlng(cp) -> Tuple[float, float]:
    """Extract (lat, lon) from a ControlPoint."""
    try:
        ll = cp.position.latlng()
        return ll.lat, ll.lng
    except Exception:
        return 0.0, 0.0


def sync_warehouses_from_game(logistics: LogisticsManager, game: Game) -> None:
    """
    Populate the LogisticsManager with a Warehouse for every blue control point.
    Existing warehouses are kept; new ones are added with default stock.
    """
    for cp in get_blue_control_points(game):
        if cp.id not in logistics._warehouses:
            logistics._warehouses[cp.id] = Warehouse(
                cp_id=cp.id,
                cp_name=cp.name,
            )
        else:
            # Keep stock but update name in case it changed
            logistics._warehouses[cp.id].cp_name = cp.name


# ======================================================================
# Drop Zone creation / edit dialog
# ======================================================================

class DropZoneDialog(QDialog):
    def __init__(
        self,
        game: Game,
        coalition: str,
        parent: Optional[QWidget] = None,
        existing: Optional[DropZone] = None,
        preselect_cp_id: Optional[int] = None,
        preset_lat: Optional[float] = None,
        preset_lon: Optional[float] = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.coalition = coalition
        self.existing = existing
        self.setWindowTitle("Edit Drop Zone" if existing else "New Drop Zone")
        self.setMinimumWidth(500)
        self._build_ui(preselect_cp_id, preset_lat, preset_lon)
        if existing:
            self._populate(existing)

    def _build_ui(
        self,
        preselect_cp_id: Optional[int],
        preset_lat: Optional[float],
        preset_lon: Optional[float],
    ) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # --- Name ---
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. LZ ALPHA")
        form.addRow("Zone name:", self.name_edit)

        # --- Type ---
        self.type_combo = QComboBox()
        self.type_combo.addItem("Troop drop zone", DropZoneType.TROOP)
        self.type_combo.addItem("Cargo drop zone", DropZoneType.CARGO)
        form.addRow("Type:", self.type_combo)

        # --- Associated base (from blue CPs) ---
        self.base_combo = QComboBox()
        self.base_combo.addItem("-- No base --", -1)
        self._blue_cps = get_blue_control_points(self.game)
        for cp in self._blue_cps:
            self.base_combo.addItem(cp.name, cp.id)
        form.addRow("Associated base:", self.base_combo)

        # --- Location ---
        loc_group = QGroupBox("Location")
        loc_layout = QVBoxLayout(loc_group)

        coord_row = QHBoxLayout()
        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(6)
        self.lat_spin.setSingleStep(0.001)
        self.lat_spin.setPrefix("Lat: ")

        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(6)
        self.lon_spin.setSingleStep(0.001)
        self.lon_spin.setPrefix("Lon: ")

        coord_row.addWidget(self.lat_spin)
        coord_row.addWidget(self.lon_spin)
        loc_layout.addLayout(coord_row)

        self.use_base_pos_btn = QPushButton("Use selected base location")
        self.use_base_pos_btn.setToolTip(
            "Auto-fill coordinates from the base selected above."
        )
        self.use_base_pos_btn.clicked.connect(self._on_use_base_pos)
        loc_layout.addWidget(self.use_base_pos_btn)

        loc_hint = QLabel(
            "Select a base above and click 'Use selected base location' to "
            "auto-fill coordinates, or enter coordinates manually."
        )
        loc_hint.setWordWrap(True)
        loc_hint.setStyleSheet("color: grey; font-size: 11px;")
        loc_layout.addWidget(loc_hint)
        form.addRow(loc_group)

        # --- Radius ---
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(100.0, 5000.0)
        self.radius_spin.setSingleStep(100.0)
        self.radius_spin.setValue(500.0)
        self.radius_spin.setSuffix(" m")
        form.addRow("Radius:", self.radius_spin)

        # --- Active ---
        self.active_check = QCheckBox("Active (include in next mission)")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)

        # --- Notes ---
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

        # Apply presets
        if preselect_cp_id is not None:
            idx = self.base_combo.findData(preselect_cp_id)
            if idx >= 0:
                self.base_combo.setCurrentIndex(idx)

        if preset_lat is not None:
            self.lat_spin.setValue(preset_lat)
        if preset_lon is not None:
            self.lon_spin.setValue(preset_lon)

    def _on_use_base_pos(self) -> None:
        cp_id = self.base_combo.currentData()
        if cp_id == -1:
            QMessageBox.information(self, "No base selected", "Please select a base first.")
            return
        cp = next((c for c in self._blue_cps if c.id == cp_id), None)
        if cp is None:
            return
        lat, lon = cp_latlng(cp)
        self.lat_spin.setValue(lat)
        self.lon_spin.setValue(lon)

    def _populate(self, dz: DropZone) -> None:
        self.name_edit.setText(dz.name)
        idx = self.type_combo.findData(dz.dz_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        idx = self.base_combo.findData(dz.cp_id)
        if idx >= 0:
            self.base_combo.setCurrentIndex(idx)
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
        cp_id = self.base_combo.currentData()
        if cp_id == -1:
            cp_id = 0
        cp = next((c for c in self._blue_cps if c.id == cp_id), None)
        cp_name = cp.name if cp else "Unknown"
        kwargs = dict(
            name=self.name_edit.text().strip().upper(),
            dz_type=self.type_combo.currentData(),
            lat=self.lat_spin.value(),
            lon=self.lon_spin.value(),
            radius_m=self.radius_spin.value(),
            cp_id=cp_id,
            cp_name=cp_name,
            coalition=self.coalition,
            active=self.active_check.isChecked(),
            notes=self.notes_edit.toPlainText(),
        )
        if self.existing:
            kwargs["dz_id"] = self.existing.dz_id
        return DropZone(**kwargs)


# ======================================================================
# Tab 1 - Drop Zones
# ======================================================================

class DropZonesTab(QWidget):
    dropZoneAdded   = Signal(object)
    dropZoneRemoved = Signal(str)
    dropZoneUpdated = Signal(object)

    def __init__(
        self, logistics: LogisticsManager, coalition: str, game: Game
    ) -> None:
        super().__init__()
        self.logistics = logistics
        self.coalition = coalition
        self.game = game
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

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

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Type", "Base", "Latitude", "Longitude", "Radius (m)", "Active", "Notes"]
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
            "Select a base when adding to associate the drop zone with that base's warehouse. "
            "Use the Logistics button in the toolbar to add a drop zone at a specific map location."
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
            cp_name = getattr(dz, "cp_name", str(dz.cp_id))
            self.table.setItem(row, 2, QTableWidgetItem(cp_name))
            self.table.setItem(row, 3, QTableWidgetItem(f"{dz.lat:.6f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{dz.lon:.6f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{dz.radius_m:.0f}"))
            active_item = QTableWidgetItem("Yes" if dz.active else "No")
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 6, active_item)
            self.table.setItem(row, 7, QTableWidgetItem(dz.notes))
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
        dlg = DropZoneDialog(game=self.game, coalition=self.coalition, parent=self)
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
            game=self.game, coalition=self.coalition, parent=self, existing=existing
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
            self, "Delete Drop Zone",
            f"Delete drop zone '{dz.name}'?\n"
            "Any planned transfers to this zone will be cancelled.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logistics.remove_drop_zone(dz_id)
            self.dropZoneRemoved.emit(dz_id)
            self.refresh()

    def add_drop_zone_at(
        self,
        lat: float,
        lon: float,
        cp_id: Optional[int] = None,
    ) -> None:
        """Open the add dialog pre-filled with a specific map location."""
        dlg = DropZoneDialog(
            game=self.game,
            coalition=self.coalition,
            parent=self,
            preselect_cp_id=cp_id,
            preset_lat=lat,
            preset_lon=lon,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dz = dlg.get_drop_zone()
            self.logistics.add_drop_zone(dz)
            self.dropZoneAdded.emit(dz)
            self.refresh()


# ======================================================================
# Tab 2 - Warehouses
# ======================================================================

class WarehouseTab(QWidget):
    def __init__(
        self, logistics: LogisticsManager, coalition: str, game: Game
    ) -> None:
        super().__init__()
        self.logistics = logistics
        self.coalition = coalition
        self.game = game
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # --- Base filter + sync ---
        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Filter by base:"))
        self.base_filter_combo = QComboBox()
        self.base_filter_combo.addItem("All bases", -1)
        self.base_filter_combo.currentIndexChanged.connect(self._on_base_filter_changed)
        base_row.addWidget(self.base_filter_combo)
        base_row.addStretch()
        self.sync_btn = QPushButton("Sync bases from map")
        self.sync_btn.setToolTip(
            "Re-read blue bases from the current campaign and add any missing warehouses."
        )
        self.sync_btn.clicked.connect(self._on_sync)
        base_row.addWidget(self.sync_btn)
        layout.addLayout(base_row)

        # --- Stock table ---
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

        # --- Direct transfer ---
        transfer_group = QGroupBox("Direct Stock Transfer (instant, no aircraft)")
        exp_layout = QFormLayout()
        self.from_combo = QComboBox()
        self.to_combo   = QComboBox()
        self.cat_combo  = QComboBox()
        for cat in WarehouseCategory:
            self.cat_combo.addItem(cat.value.replace("_", " ").title(), cat)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.0, 99999.0)
        self.amount_spin.setSingleStep(50.0)
        self.amount_spin.setDecimals(0)
        self.transfer_btn = QPushButton("Transfer Now")
        self.transfer_btn.clicked.connect(self._on_direct_transfer)
        exp_layout.addRow("From base:", self.from_combo)
        exp_layout.addRow("To base:",   self.to_combo)
        exp_layout.addRow("Category:",  self.cat_combo)
        exp_layout.addRow("Amount:",    self.amount_spin)
        exp_layout.addRow("",           self.transfer_btn)
        transfer_group.setLayout(exp_layout)
        layout.addWidget(transfer_group)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- CSV ---
        csv_group = QGroupBox("Warehouse CSV - export / import stock")
        csv_layout = QHBoxLayout()
        self.export_csv_btn = QPushButton("Export to CSV")
        self.export_csv_btn.clicked.connect(self._on_export_csv)
        self.import_csv_btn = QPushButton("Import from CSV")
        self.import_csv_btn.clicked.connect(self._on_import_csv)
        csv_layout.addWidget(self.export_csv_btn)
        csv_layout.addWidget(self.import_csv_btn)
        csv_layout.addStretch()
        csv_group.setLayout(csv_layout)
        layout.addWidget(csv_group)

    def _current_warehouses(self):
        cp_id = self.base_filter_combo.currentData()
        all_wh = self.logistics.warehouses_for_coalition(self.coalition)
        if cp_id == -1:
            return all_wh
        return [w for w in all_wh if w.cp_id == cp_id]

    def _on_base_filter_changed(self) -> None:
        self._update_table(self._current_warehouses())

    def _on_sync(self) -> None:
        sync_warehouses_from_game(self.logistics, self.game)
        self.refresh()
        self.status_label.setText(
            f"Synced - {len(self.logistics._warehouses)} blue bases loaded."
        )

    def refresh(self) -> None:
        current_cp_id = self.base_filter_combo.currentData()
        self.base_filter_combo.blockSignals(True)
        self.base_filter_combo.clear()
        self.base_filter_combo.addItem("All bases", -1)
        for wh in self.logistics.warehouses_for_coalition(self.coalition):
            self.base_filter_combo.addItem(wh.cp_name, wh.cp_id)
        idx = self.base_filter_combo.findData(current_cp_id)
        if idx >= 0:
            self.base_filter_combo.setCurrentIndex(idx)
        self.base_filter_combo.blockSignals(False)

        self._update_table(self._current_warehouses())
        self._update_transfer_combos(
            self.logistics.warehouses_for_coalition(self.coalition)
        )

    def _update_table(self, warehouses) -> None:
        cats = list(WarehouseCategory)
        self.table.setRowCount(len(warehouses))
        for row, wh in enumerate(warehouses):
            self.table.setItem(row, 0, QTableWidgetItem(wh.cp_name))
            for col, cat in enumerate(cats, start=1):
                item_data = wh.stock[cat]
                pct = (
                    int(100 * item_data.quantity / item_data.capacity)
                    if item_data.capacity else 0
                )
                cell = QTableWidgetItem(
                    f"{item_data.quantity:.0f} / {item_data.capacity:.0f} ({pct}%)"
                )
                cell.setForeground(stock_color(item_data.quantity, item_data.capacity))
                self.table.setItem(row, col, cell)

    def _update_transfer_combos(self, warehouses) -> None:
        self.from_combo.clear()
        self.to_combo.clear()
        for wh in warehouses:
            self.from_combo.addItem(wh.cp_name, wh.cp_id)
            self.to_combo.addItem(wh.cp_name, wh.cp_id)

    def _on_direct_transfer(self) -> None:
        from_cp_id = self.from_combo.currentData()
        to_cp_id   = self.to_combo.currentData()
        category   = self.cat_combo.currentData()
        amount     = self.amount_spin.value()
        if from_cp_id == to_cp_id:
            self.status_label.setText("Source and destination must differ.")
            return
        if amount <= 0:
            self.status_label.setText("Amount must be greater than zero.")
            return
        src_wh = self.logistics.get_warehouse(from_cp_id)
        dst_wh = self.logistics.get_warehouse(to_cp_id)
        if src_wh is None or dst_wh is None:
            self.status_label.setText("Warehouse not found.")
            return
        transferred = src_wh.export_to(dst_wh, category, amount)
        self.status_label.setText(
            f"Transferred {transferred:.0f} {category.value} "
            f"from {src_wh.cp_name} to {dst_wh.cp_name}"
        )
        self.refresh()

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Warehouse CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            import csv
            cats = list(WarehouseCategory)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["base"] + [c.value for c in cats])
                for wh in self.logistics.warehouses_for_coalition(self.coalition):
                    writer.writerow(
                        [wh.cp_name] + [wh.stock[c].quantity for c in cats]
                    )
            self.status_label.setText(f"Exported to: {path}")
            QMessageBox.information(self, "Export successful", f"Exported to:\n{path}")
        except Exception as e:
            self.status_label.setText("Export failed.")
            QMessageBox.critical(self, "Export failed", str(e))

    def _on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Warehouse CSV", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            import csv
            imported = 0
            warnings = []
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    base = row.get("base", "").strip()
                    wh = next(
                        (w for w in self.logistics._warehouses.values()
                         if w.cp_name == base), None
                    )
                    if wh is None:
                        warnings.append(f"Unknown base: {base}")
                        continue
                    for cat in WarehouseCategory:
                        val = row.get(cat.value, "").strip()
                        if val:
                            try:
                                wh.stock[cat].quantity = float(val)
                                imported += 1
                            except ValueError:
                                warnings.append(
                                    f"Invalid value for {base}/{cat.value}: {val}"
                                )
            self.status_label.setText(f"Imported {imported} rows.")
            self.refresh()
            if warnings:
                QMessageBox.warning(self, "Import warnings", "\n".join(warnings))
            else:
                QMessageBox.information(self, "Import successful", f"Imported {imported} rows.")
        except Exception as e:
            self.status_label.setText("Import failed.")
            QMessageBox.critical(self, "Import failed", str(e))


# ======================================================================
# Tab 3 - Transfers
# ======================================================================

class TransfersTab(QWidget):
    transferScheduled = Signal(object)

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
            self.table.setItem(row, 0, QTableWidgetItem(t.transfer_id[:8]))
            self.table.setItem(row, 1, QTableWidgetItem(
                src_wh.cp_name if src_wh else str(t.source_cp_id)
            ))
            self.table.setItem(row, 2, QTableWidgetItem(
                dst_wh.cp_name if dst_wh else str(t.dest_cp_id)
            ))
            self.table.setItem(row, 3, QTableWidgetItem(t.category.value))
            self.table.setItem(row, 4, QTableWidgetItem(f"{t.quantity:.0f}"))
            self.table.setItem(row, 5, QTableWidgetItem(
                f"{t.delivered:.0f}" if t.delivered else "-"
            ))
            status_item = QTableWidgetItem(t.status.value.capitalize())
            status_item.setForeground(STATUS_COLORS.get(t.status, QColor("white")))
            self.table.setItem(row, 6, status_item)
            self.table.setItem(row, 7, QTableWidgetItem(str(t.turn_planned)))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, t.transfer_id)

    def _on_dst_changed(self) -> None:
        dst_cp_id = self.dst_combo.currentData()
        self.dz_combo.clear()
        if dst_cp_id is not None:
            for dz in self.logistics.drop_zones_for_cp(dst_cp_id):
                if dz.active:
                    self.dz_combo.addItem(f"{dz.name} ({dz.dz_type.value})", dz.dz_id)

    def _on_schedule(self) -> None:
        src_cp_id = self.src_combo.currentData()
        dst_cp_id = self.dst_combo.currentData()
        dz_id     = self.dz_combo.currentData()
        category  = self.tcat_combo.currentData()
        quantity  = self.tamt_spin.value()
        aircraft  = self.aircraft_edit.text().strip() or "UH-1H"
        notes     = self.tnotes_edit.text().strip()
        if src_cp_id == dst_cp_id:
            self.sched_status.setText("Source and destination must differ.")
            return
        if not dz_id:
            self.sched_status.setText(
                "No active drop zone at destination. Add one in the Drop Zones tab."
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
            self.sched_status.setText("Insufficient available stock at source warehouse.")
        else:
            self.sched_status.setText(f"Transfer {transfer.transfer_id[:8]} scheduled.")
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
    def __init__(
        self, game: Optional[Game], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.setWindowTitle("Logistics & Supply Chain")
        self.setMinimumSize(960, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QLabel("Logistics & Supply Chain")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        if self.game is None:
            placeholder = QLabel(
                "No campaign is currently loaded.\n"
                "Start or load a campaign to manage logistics."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: grey; font-size: 13px;")
            layout.addWidget(placeholder)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.close)
            layout.addWidget(close_btn)
            return

        # Ensure logistics manager exists
        if not hasattr(self.game, "logistics") or self.game.logistics is None:
            from game.logistics import LogisticsManager
            self.game.logistics = LogisticsManager()

        # Auto-sync blue bases on open
        sync_warehouses_from_game(self.game.logistics, self.game)

        logistics: LogisticsManager = self.game.logistics
        coalition = "blue"
        turn = getattr(self.game, "turn", 0)

        self._tabs = QTabWidget()
        self.dz_tab = DropZonesTab(logistics, coalition, self.game)
        self._tabs.addTab(self.dz_tab, "Drop Zones")
        self.wh_tab = WarehouseTab(logistics, coalition, self.game)
        self._tabs.addTab(self.wh_tab, "Warehouses")
        self.tr_tab = TransfersTab(logistics, coalition, current_turn=turn)
        self._tabs.addTab(self.tr_tab, "Transfers")
        layout.addWidget(self._tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def open_add_drop_zone_at(
        self,
        lat: float,
        lon: float,
        cp_id: Optional[int] = None,
    ) -> None:
        """
        Called externally to open the drop zone creation dialog
        pre-filled with a specific lat/lon (e.g. from a map click).
        """
        if hasattr(self, "dz_tab"):
            self._tabs.setCurrentWidget(self.dz_tab)
            self.dz_tab.add_drop_zone_at(lat, lon, cp_id)

    def refresh(self) -> None:
        if hasattr(self, "dz_tab"):
            self.dz_tab.refresh()
        if hasattr(self, "wh_tab"):
            self.wh_tab.refresh()
        if hasattr(self, "tr_tab"):
            self.tr_tab.refresh()
