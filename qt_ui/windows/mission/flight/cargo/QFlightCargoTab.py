"""Cargo tab of a LOGISTIC flight: plan the load as part of the mission.

Pick where the cargo is loaded, the fuel, and the weapons. Weapons leave the
pickup base's stock as they are loaded (and go back when unloaded or when the
flight is deleted). The route, the weight against what the aircraft can lift,
and the resulting load sheet are shown live; the same load sheet is printed on
the flight's kneeboard.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from game import Game
from game.ato.flight import Flight
from game.ato.flightplans.planningerror import PlanningError
from game.logistics import LogisticsTransfer, WeaponInventory, build_weapon_inventory
from game.logistics.cargo import (
    FUEL_FRACTIONS,
    cargo_aircraft,
    cruise_speed_kph,
    flight_time_minutes,
    lb,
    loads_internally,
    manifest_weight_kg,
    pack_crates,
    route_legs,
    weapon_name,
    weapon_weight_kg,
)
from game.logistics.flight_cargo import (
    attach_transfer,
    fuel_fraction,
    pickup_bases,
    sync_transfer,
)
from game.logistics.transfer_flights import control_point
from game.server import EventStream
from game.sim import GameUpdateEvents

LOAD_OK_STYLE = "QProgressBar::chunk { background: #27ae60; }"
LOAD_HIGH_STYLE = "QProgressBar::chunk { background: #e67e22; }"
LOAD_OVER_STYLE = "QProgressBar::chunk { background: #c0392b; }"


class QFlightCargoTab(QWidget):
    #: The flight's fuel was changed here (the Payload tab should follow).
    fuel_changed = Signal()
    #: The pickup base changed and the flight plan was rebuilt.
    route_changed = Signal()

    def __init__(self, flight: Flight, game: Game) -> None:
        super().__init__()
        self.flight = flight
        self.game = game
        self.transfer: Optional[LogisticsTransfer] = None
        try:
            self.transfer = attach_transfer(game, flight)
        except PlanningError as ex:
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(f"This flight can't carry cargo: {ex}"))
            return
        self._build_ui()
        self.refresh()

    # ── Layout ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        route_group = QGroupBox("Route")
        route_form = QFormLayout()
        self.pickup_combo = QComboBox()
        self.pickup_combo.currentIndexChanged.connect(self._on_pickup_changed)
        self.destination_label = QLabel("")
        self.dz_combo = QComboBox()
        self.dz_combo.currentIndexChanged.connect(self._on_dz_changed)
        self.route_label = QLabel("")
        self.route_label.setWordWrap(True)
        route_form.addRow("Pick up at:", self.pickup_combo)
        route_form.addRow("Deliver to:", self.destination_label)
        route_form.addRow("Drop zone:", self.dz_combo)
        route_form.addRow("Legs:", self.route_label)
        route_group.setLayout(route_form)
        layout.addWidget(route_group)

        load_group = QGroupBox("Load")
        load_form = QFormLayout()
        fuel_row = QHBoxLayout()
        self.fuel_label = QLabel("")
        fuel_row.addWidget(self.fuel_label, 1)
        for fraction in FUEL_FRACTIONS:
            button = QPushButton(f"{fraction:.0%}")
            button.clicked.connect(lambda _=False, f=fraction: self._set_fuel(f))
            fuel_row.addWidget(button)
        load_form.addRow("Fuel:", fuel_row)

        self.weapon_combo = QComboBox()
        self.weapon_combo.setMinimumWidth(320)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 9999)
        self.count_spin.setValue(10)
        self.add_btn = QPushButton("Load")
        self.add_btn.clicked.connect(self._on_add)
        picker = QHBoxLayout()
        picker.addWidget(self.weapon_combo, 1)
        picker.addWidget(self.count_spin)
        picker.addWidget(self.add_btn)
        load_form.addRow("Add cargo:", picker)

        self.manifest_table = QTableWidget()
        self.manifest_table.setColumnCount(4)
        self.manifest_table.setHorizontalHeaderLabels(
            ["Weapon", "Qty", "Each (lb)", "Total (lb)"]
        )
        self.manifest_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.manifest_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.manifest_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        load_form.addRow("Cargo:", self.manifest_table)
        buttons = QHBoxLayout()
        self.remove_btn = QPushButton("Unload selected")
        self.remove_btn.clicked.connect(self._on_remove)
        self.clear_btn = QPushButton("Unload all")
        self.clear_btn.clicked.connect(self._on_clear)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        load_form.addRow("", buttons)

        self.load_bar = QProgressBar()
        self.load_bar.setRange(0, 100)
        self.load_label = QLabel("")
        self.load_label.setWordWrap(True)
        self.crates_label = QLabel("")
        self.crates_label.setWordWrap(True)
        load_form.addRow("Weight:", self.load_bar)
        load_form.addRow("", self.load_label)
        load_form.addRow("Crates:", self.crates_label)
        load_group.setLayout(load_form)
        layout.addWidget(load_group)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _source_inventory(self) -> Optional[WeaponInventory]:
        assert self.transfer is not None
        logistics = self.game.logistics
        inv = logistics.get_weapon_inventory(self.transfer.source_cp_id)
        if inv is None:
            cp = control_point(self.game, self.transfer.source_cp_id)
            if cp is None:
                return None
            inv = build_weapon_inventory(cp, self.game)
            logistics.set_weapon_inventory(inv)
        return inv

    def _editable(self) -> bool:
        from game.logistics import TransferStatus

        return (
            self.transfer is not None and self.transfer.status is TransferStatus.PLANNED
        )

    # ── Refresh ─────────────────────────────────────────────────────────

    def showEvent(self, event: QShowEvent) -> None:
        # Fuel may have been changed on the Payload tab.
        super().showEvent(event)
        if self.transfer is not None:
            self.refresh()

    def refresh(self) -> None:
        assert self.transfer is not None
        sync_transfer(self.transfer, self.flight)

        self.pickup_combo.blockSignals(True)
        self.pickup_combo.clear()
        for cp in pickup_bases(self.game, self.flight):
            label = cp.name + ("  (home base)" if cp is self.flight.departure else "")
            self.pickup_combo.addItem(label, cp.id)
        self.pickup_combo.setCurrentIndex(
            max(0, self.pickup_combo.findData(self.transfer.source_cp_id))
        )
        self.pickup_combo.blockSignals(False)

        destination = control_point(self.game, self.transfer.dest_cp_id)
        self.destination_label.setText(destination.name if destination else "?")
        self.dz_combo.blockSignals(True)
        self.dz_combo.clear()
        self.dz_combo.addItem("The base itself", "")
        for dz in self.game.logistics.drop_zones_for_cp(self.transfer.dest_cp_id):
            if dz.active:
                self.dz_combo.addItem(f"{dz.name} ({dz.dz_type.value})", dz.dz_id)
        self.dz_combo.setCurrentIndex(
            max(0, self.dz_combo.findData(self.transfer.dz_id))
        )
        self.dz_combo.blockSignals(False)

        editable = self._editable()
        for widget in (
            self.pickup_combo,
            self.dz_combo,
            self.weapon_combo,
            self.count_spin,
            self.add_btn,
            self.remove_btn,
            self.clear_btn,
        ):
            widget.setEnabled(editable)
        if not editable:
            self.status_label.setText(
                f"This transfer is {self.transfer.status.value}; the load can't be "
                "changed."
            )
        self._refresh_weapons()
        self._refresh_manifest()

    def _refresh_weapons(self) -> None:
        self.weapon_combo.clear()
        inv = self._source_inventory()
        entries = []
        if inv is not None:
            for item in inv.items.values():
                weight = weapon_weight_kg(item.clsid)
                if weight is not None and item.quantity > 0:
                    entries.append((item, weight))
        entries.sort(key=lambda e: (e[0].category, e[0].name))
        for item, weight in entries:
            self.weapon_combo.addItem(
                f"{item.name}  -  {lb(weight):,.0f} lb  -  {item.quantity} in stock",
                item.clsid,
            )
        if not entries:
            self.weapon_combo.addItem("No weapons in stock at this base", None)
        self.add_btn.setEnabled(self._editable() and bool(entries))

    def _refresh_manifest(self) -> None:
        assert self.transfer is not None
        cargo = self.transfer.cargo or {}
        self.manifest_table.setRowCount(len(cargo))
        for row, (clsid, count) in enumerate(cargo.items()):
            each = weapon_weight_kg(clsid) or 0.0
            name = QTableWidgetItem(weapon_name(clsid))
            name.setData(Qt.ItemDataRole.UserRole, clsid)
            self.manifest_table.setItem(row, 0, name)
            self.manifest_table.setItem(row, 1, QTableWidgetItem(str(count)))
            self.manifest_table.setItem(row, 2, QTableWidgetItem(f"{lb(each):,.0f}"))
            self.manifest_table.setItem(
                row, 3, QTableWidgetItem(f"{lb(each * count):,.0f}")
            )
        self._update_summary()

    def _update_summary(self) -> None:
        assert self.transfer is not None
        flight = self.flight
        source = control_point(self.game, self.transfer.source_cp_id)
        destination = control_point(self.game, self.transfer.dest_cp_id)
        fuel = fuel_fraction(flight)
        cargo = self.transfer.cargo or {}
        cargo_kg = manifest_weight_kg(cargo)

        self.fuel_label.setText(
            f"{lb(flight.fuel):,.0f} lb ({fuel:.0%}) - also set on the Payload tab"
        )

        if source is not None and destination is not None:
            legs = route_legs(flight.departure, source, destination)
            minutes = flight_time_minutes(legs.total, flight.unit_type)
            self.route_label.setText(
                f"{flight.departure.name} -> {source.name}: "
                f"{legs.to_pickup / 1000:,.0f} km  |  {source.name} -> "
                f"{destination.name}: {legs.pickup_to_drop / 1000:,.0f} km  |  "
                f"back: {legs.drop_to_home / 1000:,.0f} km\n"
                f"Total {legs.total / 1000:,.0f} km, about {int(minutes // 60)} h "
                f"{int(minutes % 60):02d} min at "
                f"{cruise_speed_kph(flight.unit_type):,.0f} km/h"
            )

        weights = cargo_aircraft(flight.unit_type)
        if weights is None:
            self.load_bar.setValue(0)
            self.load_bar.setFormat(f"{lb(cargo_kg):,.0f} lb")
            self.load_bar.setStyleSheet(LOAD_OK_STYLE)
            self.load_label.setText(
                "No weight data for this aircraft: load not checked. Add it to "
                "resources/logistics/cargo_aircraft.yaml."
            )
        else:
            payload = weights.payload_kg(fuel)
            share = cargo_kg / payload if payload > 0 else (1.0 if cargo_kg else 0.0)
            over = cargo_kg > payload
            self.load_bar.setValue(min(100, round(share * 100)))
            self.load_bar.setFormat(
                f"{lb(cargo_kg):,.0f} / {lb(payload):,.0f} lb ({share:.0%})"
            )
            self.load_bar.setStyleSheet(
                LOAD_OVER_STYLE
                if over
                else LOAD_HIGH_STYLE if share > 0.9 else LOAD_OK_STYLE
            )
            text = (
                f"Empty {lb(weights.empty_kg):,.0f} + fuel "
                f"{lb(fuel * weights.fuel_max_kg):,.0f} + cargo {lb(cargo_kg):,.0f} "
                f"= {lb(weights.weight_at_fuel_kg(fuel) + cargo_kg):,.0f} lb "
                f"(max {lb(weights.max_kg):,.0f} lb)"
            )
            if over:
                text += (
                    f"\nOVERWEIGHT by {lb(cargo_kg - payload):,.0f} lb: unload "
                    "cargo or take less fuel."
                )
            self.load_label.setText(text)

        crates = pack_crates(cargo, loads_internally(flight.unit_type))
        if not crates:
            where = "No cargo loaded."
        elif source is not None and source.is_fleet:
            where = "Cargo can't be placed on a ship deck: pick up at a land base."
        elif source is flight.departure:
            where = f"{len(crates)} crate(s), waiting beside the aircraft."
        else:
            where = (
                f"{len(crates)} crate(s), waiting at {source.name if source else '?'}."
            )
        self.crates_label.setText(
            where + "\nIn the mission, pilots can order more at any friendly base: "
            "F10 > Cargo."
        )

    # ── Actions ─────────────────────────────────────────────────────────

    def _set_fuel(self, fraction: float) -> None:
        self.flight.fuel = self.flight.unit_type.dcs_unit_type.fuel_max * fraction
        if self.transfer is not None:
            sync_transfer(self.transfer, self.flight)
        self._update_summary()
        self.fuel_changed.emit()

    def _on_add(self) -> None:
        assert self.transfer is not None
        clsid = self.weapon_combo.currentData()
        if clsid is None:
            return
        count = self.count_spin.value()
        weights = cargo_aircraft(self.flight.unit_type)
        if weights is not None:
            room = weights.payload_kg(fuel_fraction(self.flight)) - manifest_weight_kg(
                self.transfer.cargo or {}
            )
            each = weapon_weight_kg(clsid) or 0.0
            fits = int(room // each) if each > 0 else count
            if fits < count:
                self.status_label.setText(
                    f"Only {max(0, fits)} more fit at this fuel load."
                )
                count = max(0, fits)
        added = self.game.logistics.add_cargo(self.transfer, clsid, count)
        if added:
            self.status_label.setText(f"Loaded {added}x {weapon_name(clsid)}.")
        self._refresh_weapons()
        self._refresh_manifest()

    def _on_remove(self) -> None:
        assert self.transfer is not None
        rows = {index.row() for index in self.manifest_table.selectedIndexes()}
        for row in rows:
            item = self.manifest_table.item(row, 0)
            if item is not None:
                self.game.logistics.remove_cargo(
                    self.transfer, item.data(Qt.ItemDataRole.UserRole)
                )
        self._refresh_weapons()
        self._refresh_manifest()

    def _on_clear(self) -> None:
        assert self.transfer is not None
        for clsid in list((self.transfer.cargo or {}).keys()):
            self.game.logistics.remove_cargo(self.transfer, clsid)
        self._refresh_weapons()
        self._refresh_manifest()

    def _on_dz_changed(self) -> None:
        if self.transfer is not None:
            self.transfer.dz_id = self.dz_combo.currentData() or ""

    def _on_pickup_changed(self) -> None:
        assert self.transfer is not None
        cp_id = self.pickup_combo.currentData()
        if cp_id is None or cp_id == self.transfer.source_cp_id:
            return
        had_cargo = bool(self.transfer.cargo)
        self.game.logistics.change_pickup(self.transfer, cp_id)
        try:
            self.flight.recreate_flight_plan()
            EventStream.put_nowait(GameUpdateEvents().update_flight(self.flight))
        except PlanningError:
            logging.exception("Could not replan the LOGISTIC flight")
        self.status_label.setText(
            "Pickup changed: cargo returned to the previous base, load it again "
            "from the new one."
            if had_cargo
            else "Pickup changed."
        )
        self.route_changed.emit()
        self.refresh()
