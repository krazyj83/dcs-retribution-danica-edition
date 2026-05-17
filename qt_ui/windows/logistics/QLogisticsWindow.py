"""
qt_ui/windows/logistics/QLogisticsWindow.py

Logistics & Supply Chain window for DCS Retribution.
Four tabs:
  1. Drop Zones  - create/edit/delete drop zones for any faction base or map point
  2. Warehouses  - broad supply stock levels with base filter, sync, and CSV
  3. Inventory   - detailed per-base weapon, equipment and ground unit breakdown with CSV
  4. Transfers   - schedule, monitor, and cancel logistics deliveries

CSV formats:
  Warehouse CSV:  base, fuel, ammunition, supplies, troops
  Inventory CSV:  base, clsid, name, category, quantity, capacity
"""

from __future__ import annotations

import csv
import logging
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
    QTreeWidget,
    QTreeWidgetItem,
    QSplitter,
    QSpinBox,
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
    WeaponInventory,
    WeaponStockItem,
    build_weapon_inventory,
)

logger = logging.getLogger(__name__)

# ======================================================================
# Colours
# ======================================================================

STOCK_CRITICAL_COLOR = QColor("#c0392b")
STOCK_LOW_COLOR      = QColor("#e67e22")
STOCK_OK_COLOR       = QColor("#27ae60")
BLUE_COLOR           = QColor("#3498db")
RED_COLOR            = QColor("#e74c3c")
NEUTRAL_COLOR        = QColor("#95a5a6")

STATUS_COLORS = {
    TransferStatus.PLANNED:   QColor("#3498db"),
    TransferStatus.IN_FLIGHT: QColor("#f39c12"),
    TransferStatus.DELIVERED: QColor("#27ae60"),
    TransferStatus.FAILED:    QColor("#c0392b"),
}

CATEGORY_COLORS = {
    "Air-to-Air":                QColor("#3498db"),
    "Air-to-Ground Missile":     QColor("#e67e22"),
    "Bomb":                      QColor("#e74c3c"),
    "Rocket":                    QColor("#f39c12"),
    "Fuel Tank":                 QColor("#95a5a6"),
    "Pod":                       QColor("#9b59b6"),
    "Gun / Cannon":              QColor("#1abc9c"),
    "Anti-Ship":                 QColor("#2980b9"),
    "Armour":                    QColor("#c0392b"),
    "Air Defence":               QColor("#8e44ad"),
    "Infantry Fighting Vehicle": QColor("#d35400"),
    "Artillery":                 QColor("#e74c3c"),
    "Support Vehicle":           QColor("#7f8c8d"),
    "Radar / Command":           QColor("#16a085"),
    "Other Ground":              QColor("#95a5a6"),
    "Other":                     QColor("#7f8c8d"),
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


def cp_latlng(cp) -> Tuple[float, float]:
    try:
        ll = cp.position.latlng()
        return ll.lat, ll.lng
    except Exception:
        return 0.0, 0.0


def cp_faction(cp) -> str:
    try:
        if cp.captured.is_blue:
            return "blue"
        elif cp.captured.is_red:
            return "red"
        return "neutral"
    except Exception:
        return "neutral"


def all_control_points(game: Game) -> List:
    try:
        cps = list(game.theater.controlpoints)
        blue    = [cp for cp in cps if cp_faction(cp) == "blue"]
        red     = [cp for cp in cps if cp_faction(cp) == "red"]
        neutral = [cp for cp in cps if cp_faction(cp) == "neutral"]
        return blue + red + neutral
    except Exception:
        return []


def blue_control_points(game: Game) -> List:
    try:
        return list(game.theater.player_points())
    except Exception:
        return []


def sync_warehouses_from_game(logistics: LogisticsManager, game: Game) -> None:
    for cp in blue_control_points(game):
        if cp.id not in logistics._warehouses:
            logistics._warehouses[cp.id] = Warehouse(cp_id=cp.id, cp_name=cp.name)
        else:
            logistics._warehouses[cp.id].cp_name = cp.name


# ======================================================================
# CSV helpers
# ======================================================================

WAREHOUSE_CSV_COLUMNS = ["base"] + [c.value for c in WarehouseCategory]
INVENTORY_CSV_COLUMNS = ["base", "clsid", "name", "category", "quantity", "capacity"]


def export_warehouse_csv(logistics: LogisticsManager, path: str) -> int:
    """Export broad warehouse stock. Returns number of rows written."""
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WAREHOUSE_CSV_COLUMNS)
        writer.writeheader()
        for wh in logistics.warehouses_for_coalition("blue"):
            row = {"base": wh.cp_name}
            for cat in WarehouseCategory:
                row[cat.value] = f"{wh.stock[cat].quantity:.1f}"
            writer.writerow(row)
            rows += 1
    return rows


def import_warehouse_csv(logistics: LogisticsManager, path: str) -> Tuple[int, List[str]]:
    """
    Import broad warehouse stock from CSV.
    Returns (rows_imported, warnings).
    """
    imported = 0
    warnings: List[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Validate columns
        if reader.fieldnames and "base" not in reader.fieldnames:
            raise ValueError(
                "CSV missing 'base' column. "
                "Expected columns: " + ", ".join(WAREHOUSE_CSV_COLUMNS)
            )
        for row in reader:
            base = row.get("base", "").strip()
            wh = next(
                (w for w in logistics._warehouses.values() if w.cp_name == base),
                None,
            )
            if wh is None:
                warnings.append(f"Unknown base '{base}' — skipped")
                continue
            for cat in WarehouseCategory:
                val = row.get(cat.value, "").strip()
                if not val:
                    continue
                try:
                    wh.stock[cat].quantity = float(val)
                    imported += 1
                except ValueError:
                    warnings.append(
                        f"Invalid value for {base}/{cat.value}: '{val}' — skipped"
                    )
    return imported, warnings


def export_inventory_csv(logistics: LogisticsManager, path: str) -> int:
    """
    Export detailed weapon/equipment inventory.
    One row per weapon/item per base.
    Returns number of rows written.
    """
    rows = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTORY_CSV_COLUMNS)
        writer.writeheader()
        for inv in logistics._weapon_inventories.values():
            for item in sorted(inv.items.values(), key=lambda i: (i.category, i.name)):
                writer.writerow({
                    "base":     inv.cp_name,
                    "clsid":    item.clsid,
                    "name":     item.name,
                    "category": item.category,
                    "quantity": item.quantity,
                    "capacity": item.capacity,
                })
                rows += 1
    return rows


def import_inventory_csv(logistics: LogisticsManager, path: str) -> Tuple[int, List[str]]:
    """
    Import detailed weapon/equipment inventory from CSV.
    Matches rows by base name + clsid. Creates new items if not found.
    Returns (rows_imported, warnings).
    """
    imported = 0
    warnings: List[str] = []

    # Build a lookup: cp_name → WeaponInventory
    inv_by_name = {inv.cp_name: inv for inv in logistics._weapon_inventories.values()}

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "base" not in reader.fieldnames:
            raise ValueError(
                "CSV missing 'base' column. "
                "Expected columns: " + ", ".join(INVENTORY_CSV_COLUMNS)
            )
        for row in reader:
            base     = row.get("base", "").strip()
            clsid    = row.get("clsid", "").strip()
            name     = row.get("name", "").strip()
            category = row.get("category", "Other").strip()
            qty_str  = row.get("quantity", "").strip()
            cap_str  = row.get("capacity", "").strip()

            if not base or not clsid:
                warnings.append(f"Row missing base or clsid — skipped: {row}")
                continue

            inv = inv_by_name.get(base)
            if inv is None:
                warnings.append(f"Unknown base '{base}' — skipped")
                continue

            try:
                qty = int(float(qty_str)) if qty_str else 0
            except ValueError:
                warnings.append(f"Invalid quantity for {base}/{name}: '{qty_str}' — skipped")
                continue

            try:
                cap = int(float(cap_str)) if cap_str else 50
            except ValueError:
                cap = 50

            if clsid in inv.items:
                inv.items[clsid].quantity = qty
                inv.items[clsid].capacity = cap
            else:
                # Create new item from CSV data
                from game.logistics import WeaponStockItem
                inv.items[clsid] = WeaponStockItem(
                    name=name or clsid,
                    clsid=clsid,
                    category=category,
                    quantity=qty,
                    capacity=cap,
                )
            imported += 1

    return imported, warnings


# ======================================================================
# Map point picker
# ======================================================================

class MapPointPickerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enter Map Coordinates")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        info = QLabel(
            "Enter the latitude and longitude of the drop zone.\n"
            "Read coordinates from DCS by right-clicking the map."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(info)
        form = QFormLayout()
        self.lat_spin = QDoubleSpinBox()
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(6)
        self.lat_spin.setSingleStep(0.001)
        self.lon_spin = QDoubleSpinBox()
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(6)
        self.lon_spin.setSingleStep(0.001)
        form.addRow("Latitude:", self.lat_spin)
        form.addRow("Longitude:", self.lon_spin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_latlng(self) -> Tuple[float, float]:
        return self.lat_spin.value(), self.lon_spin.value()


# ======================================================================
# Drop Zone dialog
# ======================================================================

class DropZoneDialog(QDialog):
    def __init__(
        self,
        game: Game,
        parent: Optional[QWidget] = None,
        existing: Optional[DropZone] = None,
        preselect_cp_id: Optional[int] = None,
        preset_lat: Optional[float] = None,
        preset_lon: Optional[float] = None,
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.existing = existing
        self._all_cps = all_control_points(game)
        self.setWindowTitle("Edit Drop Zone" if existing else "New Drop Zone")
        self.setMinimumWidth(520)
        self._build_ui(preselect_cp_id, preset_lat, preset_lon)
        if existing:
            self._populate(existing)

    def _build_ui(self, preselect_cp_id, preset_lat, preset_lon) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. LZ ALPHA")
        form.addRow("Zone name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Troop drop zone", DropZoneType.TROOP)
        self.type_combo.addItem("Cargo drop zone", DropZoneType.CARGO)
        form.addRow("Type:", self.type_combo)

        self.base_combo = QComboBox()
        self.base_combo.addItem("-- Custom map point --", -1)
        for cp in self._all_cps:
            faction = cp_faction(cp)
            self.base_combo.addItem(f"[{faction.upper()}] {cp.name}", cp.id)
        form.addRow("Associated base:", self.base_combo)

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
        btn_row = QHBoxLayout()
        self.use_base_btn = QPushButton("Use selected base location")
        self.use_base_btn.clicked.connect(self._on_use_base_pos)
        self.pick_map_btn = QPushButton("Enter map coordinates...")
        self.pick_map_btn.clicked.connect(self._on_pick_map)
        btn_row.addWidget(self.use_base_btn)
        btn_row.addWidget(self.pick_map_btn)
        loc_layout.addLayout(btn_row)
        loc_hint = QLabel("Tip: Read coordinates from DCS by right-clicking the map.")
        loc_hint.setWordWrap(True)
        loc_hint.setStyleSheet("color: grey; font-size: 11px;")
        loc_layout.addWidget(loc_hint)
        form.addRow(loc_group)

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
        self.notes_edit.setMaximumHeight(70)
        self.notes_edit.setPlaceholderText("Optional notes...")
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
            QMessageBox.information(self, "No base", "Please select a base first.")
            return
        cp = next((c for c in self._all_cps if c.id == cp_id), None)
        if cp:
            lat, lon = cp_latlng(cp)
            self.lat_spin.setValue(lat)
            self.lon_spin.setValue(lon)

    def _on_pick_map(self) -> None:
        dlg = MapPointPickerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            lat, lon = dlg.get_latlng()
            self.lat_spin.setValue(lat)
            self.lon_spin.setValue(lon)
            self.base_combo.setCurrentIndex(0)

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
        cp = next((c for c in self._all_cps if c.id == cp_id), None)
        return DropZone(
            name=self.name_edit.text().strip().upper(),
            dz_type=self.type_combo.currentData(),
            lat=self.lat_spin.value(),
            lon=self.lon_spin.value(),
            radius_m=self.radius_spin.value(),
            cp_id=cp_id,
            cp_name=cp.name if cp else "Custom point",
            coalition=cp_faction(cp) if cp else "blue",
            active=self.active_check.isChecked(),
            notes=self.notes_edit.toPlainText(),
            **({"dz_id": self.existing.dz_id} if self.existing else {}),
        )


# ======================================================================
# Tab 1 - Drop Zones
# ======================================================================

class DropZonesTab(QWidget):
    dropZoneAdded   = Signal(object)
    dropZoneRemoved = Signal(str)
    dropZoneUpdated = Signal(object)

    def __init__(self, logistics: LogisticsManager, game: Game) -> None:
        super().__init__()
        self.logistics = logistics
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
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Name", "Type", "Faction", "Base",
            "Latitude", "Longitude", "Radius (m)", "Active", "Notes"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        info = QLabel(
            "Drop zones can be placed at any base (blue, red, or neutral) "
            "or at a custom map coordinate."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(info)

    def refresh(self) -> None:
        dzs = list(self.logistics._drop_zones.values())
        self.table.setRowCount(len(dzs))
        for row, dz in enumerate(dzs):
            self.table.setItem(row, 0, QTableWidgetItem(dz.name))
            type_item = QTableWidgetItem(dz.dz_type.value.capitalize())
            type_item.setForeground(
                QColor("#e67e22") if dz.dz_type == DropZoneType.TROOP
                else QColor("#3498db")
            )
            self.table.setItem(row, 1, type_item)
            faction = getattr(dz, "coalition", "blue")
            faction_item = QTableWidgetItem(faction.upper())
            faction_item.setForeground(
                BLUE_COLOR if faction == "blue"
                else RED_COLOR if faction == "red"
                else NEUTRAL_COLOR
            )
            self.table.setItem(row, 2, faction_item)
            self.table.setItem(row, 3, QTableWidgetItem(getattr(dz, "cp_name", "")))
            self.table.setItem(row, 4, QTableWidgetItem(f"{dz.lat:.6f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{dz.lon:.6f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"{dz.radius_m:.0f}"))
            active_item = QTableWidgetItem("Yes" if dz.active else "No")
            active_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 7, active_item)
            self.table.setItem(row, 8, QTableWidgetItem(dz.notes))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, dz.dz_id)

    def _selected_dz_id(self) -> Optional[str]:
        if not self.table.selectedItems():
            return None
        return self.table.item(self.table.currentRow(), 0).data(Qt.ItemDataRole.UserRole)

    def _on_selection_changed(self) -> None:
        has = bool(self.table.selectedItems())
        self.edit_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)

    def _on_add(self) -> None:
        dlg = DropZoneDialog(game=self.game, parent=self)
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
        dlg = DropZoneDialog(game=self.game, parent=self, existing=existing)
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
            f"Delete drop zone '{dz.name}'?\nPlanned transfers will be cancelled.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logistics.remove_drop_zone(dz_id)
            self.dropZoneRemoved.emit(dz_id)
            self.refresh()

    def add_drop_zone_at(
        self, lat: float, lon: float, cp_id: Optional[int] = None
    ) -> None:
        dlg = DropZoneDialog(
            game=self.game, parent=self,
            preselect_cp_id=cp_id, preset_lat=lat, preset_lon=lon,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dz = dlg.get_drop_zone()
            self.logistics.add_drop_zone(dz)
            self.dropZoneAdded.emit(dz)
            self.refresh()


# ======================================================================
# Tab 2 - Warehouses (broad stock) with corrected CSV
# ======================================================================

class WarehouseTab(QWidget):
    def __init__(self, logistics: LogisticsManager, game: Game) -> None:
        super().__init__()
        self.logistics = logistics
        self.game = game
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        base_row = QHBoxLayout()
        base_row.addWidget(QLabel("Filter by base:"))
        self.base_filter_combo = QComboBox()
        self.base_filter_combo.addItem("All bases", -1)
        self.base_filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        base_row.addWidget(self.base_filter_combo)
        base_row.addStretch()
        self.sync_btn = QPushButton("Sync bases from campaign")
        self.sync_btn.clicked.connect(self._on_sync)
        base_row.addWidget(self.sync_btn)
        layout.addLayout(base_row)

        self.table = QTableWidget()
        cats = list(WarehouseCategory)
        self.table.setColumnCount(1 + len(cats))
        self.table.setHorizontalHeaderLabels(
            ["Base"] + [c.value.replace("_", " ").title() for c in cats]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

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

        # CSV — uses WAREHOUSE_CSV_COLUMNS format
        csv_group = QGroupBox(
            f"Warehouse CSV  (columns: {', '.join(WAREHOUSE_CSV_COLUMNS)})"
        )
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
        all_wh = self.logistics.warehouses_for_coalition("blue")
        return all_wh if cp_id == -1 else [w for w in all_wh if w.cp_id == cp_id]

    def _on_filter_changed(self) -> None:
        self._update_table(self._current_warehouses())

    def _on_sync(self) -> None:
        sync_warehouses_from_game(self.logistics, self.game)
        self.refresh()
        self.status_label.setText(
            f"Synced — {len(self.logistics._warehouses)} blue bases loaded."
        )

    def refresh(self) -> None:
        current = self.base_filter_combo.currentData()
        self.base_filter_combo.blockSignals(True)
        self.base_filter_combo.clear()
        self.base_filter_combo.addItem("All bases", -1)
        for wh in self.logistics.warehouses_for_coalition("blue"):
            self.base_filter_combo.addItem(wh.cp_name, wh.cp_id)
        idx = self.base_filter_combo.findData(current)
        if idx >= 0:
            self.base_filter_combo.setCurrentIndex(idx)
        self.base_filter_combo.blockSignals(False)
        self._update_table(self._current_warehouses())
        self._update_transfer_combos()

    def _update_table(self, warehouses) -> None:
        cats = list(WarehouseCategory)
        self.table.setRowCount(len(warehouses))
        for row, wh in enumerate(warehouses):
            self.table.setItem(row, 0, QTableWidgetItem(wh.cp_name))
            for col, cat in enumerate(cats, start=1):
                sd = wh.stock[cat]
                pct = int(100 * sd.quantity / sd.capacity) if sd.capacity else 0
                cell = QTableWidgetItem(
                    f"{sd.quantity:.0f} / {sd.capacity:.0f} ({pct}%)"
                )
                cell.setForeground(stock_color(sd.quantity, sd.capacity))
                self.table.setItem(row, col, cell)

    def _update_transfer_combos(self) -> None:
        self.from_combo.clear()
        self.to_combo.clear()
        for wh in self.logistics.warehouses_for_coalition("blue"):
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
        src = self.logistics.get_warehouse(from_cp_id)
        dst = self.logistics.get_warehouse(to_cp_id)
        if src is None or dst is None:
            self.status_label.setText("Warehouse not found.")
            return
        transferred = src.export_to(dst, category, amount)
        self.status_label.setText(
            f"Transferred {transferred:.0f} {category.value} "
            f"from {src.cp_name} to {dst.cp_name}"
        )
        self.refresh()

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Warehouse Stock CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            rows = export_warehouse_csv(self.logistics, path)
            self.status_label.setText(f"Exported {rows} bases to: {path}")
            QMessageBox.information(
                self, "Export successful",
                f"Exported {rows} bases.\n\nColumns: {', '.join(WAREHOUSE_CSV_COLUMNS)}"
            )
        except Exception as e:
            logger.exception("Warehouse CSV export failed")
            QMessageBox.critical(self, "Export failed", str(e))

    def _on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Warehouse Stock CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            imported, warnings = import_warehouse_csv(self.logistics, path)
            self.status_label.setText(f"Imported {imported} stock values.")
            self.refresh()
            msg = f"Imported {imported} stock values from:\n{path}"
            if warnings:
                msg += f"\n\n{len(warnings)} warning(s):\n" + "\n".join(warnings)
                QMessageBox.warning(self, "Import complete with warnings", msg)
            else:
                QMessageBox.information(self, "Import successful", msg)
        except ValueError as e:
            QMessageBox.critical(self, "Import failed — wrong format", str(e))
        except Exception as e:
            logger.exception("Warehouse CSV import failed")
            QMessageBox.critical(self, "Import failed", str(e))


# ======================================================================
# Tab 3 - Detailed Weapon & Equipment Inventory with CSV
# ======================================================================

class InventoryTab(QWidget):
    def __init__(self, logistics: LogisticsManager, game: Game) -> None:
        super().__init__()
        self.logistics = logistics
        self.game = game
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Base:"))
        self.base_combo = QComboBox()
        self.base_combo.currentIndexChanged.connect(self._on_base_changed)
        top_row.addWidget(self.base_combo)
        top_row.addStretch()
        self.sync_btn = QPushButton("Sync inventory from campaign")
        self.sync_btn.clicked.connect(self._on_sync)
        top_row.addWidget(self.sync_btn)
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.category_tree = QTreeWidget()
        self.category_tree.setHeaderLabel("Categories")
        self.category_tree.setMaximumWidth(220)
        self.category_tree.itemSelectionChanged.connect(self._on_category_selected)
        splitter.addWidget(self.category_tree)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.items_table = QTableWidget()
        self.items_table.setColumnCount(4)
        self.items_table.setHorizontalHeaderLabels([
            "Item", "Category", "Quantity", "Capacity"
        ])
        self.items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for col in (1, 2, 3):
            self.items_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.items_table)

        edit_group = QGroupBox("Edit selected item quantity")
        edit_layout = QHBoxLayout()
        edit_layout.addWidget(QLabel("New quantity:"))
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 9999)
        edit_layout.addWidget(self.qty_spin)
        self.apply_qty_btn = QPushButton("Apply")
        self.apply_qty_btn.clicked.connect(self._on_apply_qty)
        edit_layout.addWidget(self.apply_qty_btn)
        edit_layout.addStretch()
        self.zero_all_btn = QPushButton("Zero all (simulate capture)")
        self.zero_all_btn.clicked.connect(self._on_zero_all)
        edit_layout.addWidget(self.zero_all_btn)
        edit_group.setLayout(edit_layout)
        right_layout.addWidget(edit_group)

        # CSV — uses INVENTORY_CSV_COLUMNS format
        csv_group = QGroupBox(
            f"Inventory CSV  (columns: {', '.join(INVENTORY_CSV_COLUMNS)})"
        )
        csv_layout = QHBoxLayout()
        self.export_inv_btn = QPushButton("Export all bases to CSV")
        self.export_inv_btn.setToolTip(
            "Export the full weapon/equipment inventory for all bases to a CSV file."
        )
        self.export_inv_btn.clicked.connect(self._on_export_csv)

        self.import_inv_btn = QPushButton("Import from CSV")
        self.import_inv_btn.setToolTip(
            "Import weapon/equipment quantities from a CSV file. "
            "Matches by base name and CLSID. New items are created if not found."
        )
        self.import_inv_btn.clicked.connect(self._on_import_csv)

        csv_layout.addWidget(self.export_inv_btn)
        csv_layout.addWidget(self.import_inv_btn)
        csv_layout.addStretch()
        csv_group.setLayout(csv_layout)
        right_layout.addWidget(csv_group)

        self.status_label = QLabel("")
        right_layout.addWidget(self.status_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([200, 600])
        layout.addWidget(splitter)

        hint = QLabel(
            "Inventory is derived from squadrons at each base and their available "
            "weapon types, plus ground units from the base garrison. "
            "Export to CSV to edit quantities in a spreadsheet, then import back."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(hint)

    def _on_sync(self) -> None:
        self.logistics.sync_weapon_inventories(self.game)
        self.refresh()
        self.status_label.setText("Weapon inventories synced from campaign.")

    def refresh(self) -> None:
        current_cp_id = self.base_combo.currentData()
        self.base_combo.blockSignals(True)
        self.base_combo.clear()
        self.base_combo.addItem("-- Select base --", -1)
        for wh in self.logistics.warehouses_for_coalition("blue"):
            self.base_combo.addItem(wh.cp_name, wh.cp_id)
        idx = self.base_combo.findData(current_cp_id)
        if idx >= 0:
            self.base_combo.setCurrentIndex(idx)
        self.base_combo.blockSignals(False)
        self._refresh_view()

    def _on_base_changed(self) -> None:
        self._refresh_view()

    def _refresh_view(self) -> None:
        self.category_tree.clear()
        self.items_table.setRowCount(0)
        cp_id = self.base_combo.currentData()
        if cp_id == -1:
            return

        inv = self.logistics.get_weapon_inventory(cp_id)
        if inv is None:
            cp = next(
                (cp for cp in blue_control_points(self.game) if cp.id == cp_id), None
            )
            if cp:
                inv = build_weapon_inventory(cp, self.game)
                self.logistics.set_weapon_inventory(inv)
            else:
                return

        by_cat = inv.items_by_category()

        total_node = QTreeWidgetItem(self.category_tree)
        total_node.setText(0, f"All ({len(inv.items)})")
        total_node.setData(0, Qt.ItemDataRole.UserRole, "__all__")
        font = QFont()
        font.setBold(True)
        total_node.setFont(0, font)

        for cat, items in by_cat.items():
            node = QTreeWidgetItem(self.category_tree)
            node.setText(0, f"{cat} ({len(items)})")
            node.setData(0, Qt.ItemDataRole.UserRole, cat)
            node.setForeground(0, CATEGORY_COLORS.get(cat, NEUTRAL_COLOR))

        self.category_tree.expandAll()
        self._show_items(list(inv.items.values()))

    def _on_category_selected(self) -> None:
        items = self.category_tree.selectedItems()
        if not items:
            return
        cp_id = self.base_combo.currentData()
        if cp_id == -1:
            return
        inv = self.logistics.get_weapon_inventory(cp_id)
        if inv is None:
            return
        cat_key = items[0].data(0, Qt.ItemDataRole.UserRole)
        if cat_key == "__all__":
            self._show_items(list(inv.items.values()))
        else:
            self._show_items([i for i in inv.items.values() if i.category == cat_key])

    def _show_items(self, items: List[WeaponStockItem]) -> None:
        items_sorted = sorted(items, key=lambda i: (i.category, i.name))
        self.items_table.setRowCount(len(items_sorted))
        for row, item in enumerate(items_sorted):
            name_cell = QTableWidgetItem(item.name)
            name_cell.setData(Qt.ItemDataRole.UserRole, item.clsid)
            self.items_table.setItem(row, 0, name_cell)

            cat_cell = QTableWidgetItem(item.category)
            cat_cell.setForeground(CATEGORY_COLORS.get(item.category, NEUTRAL_COLOR))
            self.items_table.setItem(row, 1, cat_cell)

            qty_cell = QTableWidgetItem(str(item.quantity))
            qty_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_cell.setForeground(
                STOCK_CRITICAL_COLOR if item.quantity == 0
                else STOCK_LOW_COLOR if item.quantity < item.capacity * 0.3
                else STOCK_OK_COLOR
            )
            self.items_table.setItem(row, 2, qty_cell)

            cap_cell = QTableWidgetItem(str(item.capacity))
            cap_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.items_table.setItem(row, 3, cap_cell)

    def _on_apply_qty(self) -> None:
        selected = self.items_table.selectedItems()
        if not selected:
            self.status_label.setText("Select an item first.")
            return
        cp_id = self.base_combo.currentData()
        inv = self.logistics.get_weapon_inventory(cp_id)
        if inv is None:
            return
        clsid = self.items_table.item(
            self.items_table.currentRow(), 0
        ).data(Qt.ItemDataRole.UserRole)
        if clsid in inv.items:
            inv.items[clsid].quantity = self.qty_spin.value()
            self._refresh_view()
            self.status_label.setText(
                f"Updated {inv.items[clsid].name} → {self.qty_spin.value()}"
            )

    def _on_zero_all(self) -> None:
        cp_id = self.base_combo.currentData()
        if cp_id == -1:
            return
        inv = self.logistics.get_weapon_inventory(cp_id)
        if inv is None:
            return
        reply = QMessageBox.question(
            self, "Zero inventory",
            "Set all weapon and equipment quantities to zero for this base?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            inv.zero_all()
            self._refresh_view()
            self.status_label.setText("All quantities set to zero.")

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Inventory CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            rows = export_inventory_csv(self.logistics, path)
            self.status_label.setText(f"Exported {rows} items to: {path}")
            QMessageBox.information(
                self, "Export successful",
                f"Exported {rows} weapon/equipment items.\n\n"
                f"Columns: {', '.join(INVENTORY_CSV_COLUMNS)}\n\n"
                f"Edit quantities in the 'quantity' column, then import back."
            )
        except Exception as e:
            logger.exception("Inventory CSV export failed")
            QMessageBox.critical(self, "Export failed", str(e))

    def _on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Inventory CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            imported, warnings = import_inventory_csv(self.logistics, path)
            self.status_label.setText(f"Imported {imported} items.")
            self._refresh_view()
            msg = f"Imported {imported} weapon/equipment quantities from:\n{path}"
            if warnings:
                msg += f"\n\n{len(warnings)} warning(s):\n" + "\n".join(warnings)
                QMessageBox.warning(self, "Import complete with warnings", msg)
            else:
                QMessageBox.information(self, "Import successful", msg)
        except ValueError as e:
            QMessageBox.critical(self, "Import failed — wrong format", str(e))
        except Exception as e:
            logger.exception("Inventory CSV import failed")
            QMessageBox.critical(self, "Import failed", str(e))


# ======================================================================
# Tab 4 - Transfers
# ======================================================================

class TransfersTab(QWidget):
    transferScheduled = Signal(object)

    def __init__(self, logistics: LogisticsManager, current_turn: int = 0) -> None:
        super().__init__()
        self.logistics = logistics
        self.current_turn = current_turn
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        sched_group = QGroupBox("Schedule New Transfer")
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
        self.tnotes_edit = QLineEdit()
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        warehouses = self.logistics.warehouses_for_coalition("blue")
        for combo in (self.src_combo, self.dst_combo):
            combo.clear()
            for wh in warehouses:
                combo.addItem(wh.cp_name, wh.cp_id)
        self._on_dst_changed()
        all_transfers = list(self.logistics._transfers.values())
        self.table.setRowCount(len(all_transfers))
        for row, t in enumerate(all_transfers):
            src = self.logistics.get_warehouse(t.source_cp_id)
            dst = self.logistics.get_warehouse(t.dest_cp_id)
            self.table.setItem(row, 0, QTableWidgetItem(t.transfer_id[:8]))
            self.table.setItem(row, 1, QTableWidgetItem(
                src.cp_name if src else str(t.source_cp_id)
            ))
            self.table.setItem(row, 2, QTableWidgetItem(
                dst.cp_name if dst else str(t.dest_cp_id)
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
            self.sched_status.setText("Source and destination must differ.")
            return
        if not dz_id:
            self.sched_status.setText("No active drop zone at destination.")
            return
        transfer = self.logistics.schedule_transfer(
            source_cp_id=src_cp_id, dest_cp_id=dst_cp_id, dz_id=dz_id,
            category=category, quantity=quantity, aircraft_type=aircraft,
            turn=self.current_turn, notes=notes,
        )
        if transfer is None:
            self.sched_status.setText("Insufficient stock at source.")
        else:
            self.sched_status.setText(
                f"Transfer {transfer.transfer_id[:8]} scheduled."
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
    def __init__(
        self, game: Optional[Game], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.game = game
        self.setWindowTitle("Logistics & Supply Chain")
        self.setMinimumSize(1060, 740)
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

        if not hasattr(self.game, "logistics") or self.game.logistics is None:
            from game.logistics import LogisticsManager
            self.game.logistics = LogisticsManager()

        sync_warehouses_from_game(self.game.logistics, self.game)

        logistics = self.game.logistics
        turn = getattr(self.game, "turn", 0)

        self._tabs = QTabWidget()
        self.dz_tab  = DropZonesTab(logistics, self.game)
        self.wh_tab  = WarehouseTab(logistics, self.game)
        self.inv_tab = InventoryTab(logistics, self.game)
        self.tr_tab  = TransfersTab(logistics, current_turn=turn)

        self._tabs.addTab(self.dz_tab,  "Drop Zones")
        self._tabs.addTab(self.wh_tab,  "Warehouses")
        self._tabs.addTab(self.inv_tab, "Inventory")
        self._tabs.addTab(self.tr_tab,  "Transfers")
        layout.addWidget(self._tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def open_add_drop_zone_at(
        self, lat: float, lon: float, cp_id: Optional[int] = None
    ) -> None:
        if hasattr(self, "dz_tab"):
            self._tabs.setCurrentWidget(self.dz_tab)
            self.dz_tab.add_drop_zone_at(lat, lon, cp_id)

    def refresh(self) -> None:
        for attr in ("dz_tab", "wh_tab", "inv_tab", "tr_tab"):
            tab = getattr(self, attr, None)
            if tab and hasattr(tab, "refresh"):
                tab.refresh()
