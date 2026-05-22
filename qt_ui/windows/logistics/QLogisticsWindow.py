# ======================================================================
# Tab 2 - Warehouses
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

        # ── Per-category restock (main base only) ─────────────────────
        self._cat_restock_btns: dict = {}   # WarehouseCategory -> QPushButton
        cat_restock_group = QGroupBox("Restock Individual Category (Main Base only)")
        cat_restock_layout = QHBoxLayout()
        for cat in WarehouseCategory:
            btn = QPushButton(f"Restock {cat.value.title()}")
            btn.setStyleSheet(RESTOCK_STYLE)
            btn.setEnabled(False)
            btn.setToolTip(
                f"Restock {cat.value} to full capacity at the main base.\n"
                f"Rate: $0.05M per unit deficit. Cost deducted from budget."
            )
            # Use a default-arg capture to bind cat correctly in the lambda
            btn.clicked.connect(
                lambda checked=False, c=cat: self._on_restock_category(c)
            )
            cat_restock_layout.addWidget(btn)
            self._cat_restock_btns[cat] = btn
        cat_restock_group.setLayout(cat_restock_layout)
        layout.addWidget(cat_restock_group)

        # ── CSV + full restock row ────────────────────────────────────
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
        self.restock_wh_btn = QPushButton("Restock ALL to Full (Main Base only)")
        self.restock_wh_btn.setToolTip(
            "Refill ALL warehouse categories to full capacity.\n"
            "Cost: $0.05M per unit deficit. Deducted from budget.\n"
            "Only available when the main base is selected in the filter."
        )
        self.restock_wh_btn.setStyleSheet(RESTOCK_STYLE)
        self.restock_wh_btn.setEnabled(False)
        self.restock_wh_btn.clicked.connect(self._on_restock)
        csv_layout.addWidget(self.restock_wh_btn)
        csv_group.setLayout(csv_layout)
        layout.addWidget(csv_group)

    def _current_warehouses(self):
        cp_id = self.base_filter_combo.currentData()
        all_wh = self.logistics.warehouses_for_coalition("blue")
        return all_wh if cp_id == -1 else [w for w in all_wh if w.cp_id == cp_id]

    def _on_filter_changed(self) -> None:
        self._update_table(self._current_warehouses())
        cp_id = self.base_filter_combo.currentData()
        is_main = cp_id != -1 and self.logistics.is_main_base(cp_id)
        self.restock_wh_btn.setEnabled(is_main)
        # Enable/disable per-category buttons and update their tooltips
        for cat, btn in self._cat_restock_btns.items():
            btn.setEnabled(is_main)
            if is_main:
                cost = self.logistics.restock_warehouse_category_cost(cp_id, cat)
                budget = self.game.blue.budget if self.game else 0
                wh = self.logistics.get_warehouse(cp_id)
                if wh:
                    sd = wh.stock[cat]
                    deficit = max(0.0, sd.capacity - sd.quantity)
                    btn.setToolTip(
                        f"Restock {cat.value} to full capacity.\n"
                        f"Current: {sd.quantity:.0f} / {sd.capacity:.0f}  "
                        f"(deficit: {deficit:.0f})\n"
                        f"Cost: ${cost:.2f}M  |  Budget: ${budget:.1f}M"
                    )
        if is_main:
            cost = self.logistics.restock_warehouse_cost(cp_id)
            budget = self.game.blue.budget if self.game else 0
            self.restock_wh_btn.setToolTip(
                f"Restock ALL categories to full capacity.\n"
                f"Total cost: ${cost:.1f}M  |  Budget: ${budget:.1f}M\n"
                f"Rate: $0.05M per unit deficit."
            )

    def _on_sync(self) -> None:
        sync_warehouses_from_game(self.logistics, self.game)
        self.refresh()
        self.status_label.setText(
            f"Synced - {len(self.logistics._warehouses)} blue bases loaded."
        )

    def refresh(self) -> None:
        current = self.base_filter_combo.currentData()
        self.base_filter_combo.blockSignals(True)
        self.base_filter_combo.clear()
        self.base_filter_combo.addItem("All bases", -1)
        for wh in self.logistics.warehouses_for_coalition("blue"):
            label = f"[MAIN] {wh.cp_name}" if self.logistics.is_main_base(wh.cp_id) else wh.cp_name
            self.base_filter_combo.addItem(label, wh.cp_id)
        idx = self.base_filter_combo.findData(current)
        if idx >= 0:
            self.base_filter_combo.setCurrentIndex(idx)
        self.base_filter_combo.blockSignals(False)
        self._update_table(self._current_warehouses())
        self._update_transfer_combos()
        cp_id = self.base_filter_combo.currentData()
        is_main = cp_id != -1 and self.logistics.is_main_base(cp_id)
        self.restock_wh_btn.setEnabled(is_main)
        for btn in self._cat_restock_btns.values():
            btn.setEnabled(is_main)

    def _update_table(self, warehouses) -> None:
        cats = list(WarehouseCategory)
        self.table.setRowCount(len(warehouses))
        for row, wh in enumerate(warehouses):
            name = f"[MAIN] {wh.cp_name}" if self.logistics.is_main_base(wh.cp_id) else wh.cp_name
            self.table.setItem(row, 0, QTableWidgetItem(name))
            for col, cat in enumerate(cats, start=1):
                sd = wh.stock[cat]
                pct = int(100 * sd.quantity / sd.capacity) if sd.capacity else 0
                cell = QTableWidgetItem(f"{sd.quantity:.0f} / {sd.capacity:.0f} ({pct}%)")
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

    def _on_restock_category(self, category: WarehouseCategory) -> None:
        """Restock a single warehouse category to capacity (main base only)."""
        cp_id = self.base_filter_combo.currentData()
        if cp_id == -1 or not self.logistics.is_main_base(cp_id):
            QMessageBox.warning(self, "Main base only",
                "Per-category restock is only available at the designated main base.\n"
                "Set a main base in the Main Base tab first.")
            return
        wh = self.logistics.get_warehouse(cp_id)
        if wh is None:
            return
        sd = wh.stock[category]
        deficit = max(0.0, sd.capacity - sd.quantity)
        if deficit <= 0:
            QMessageBox.information(self, "Already full",
                f"{category.value.title()} is already at capacity "
                f"({sd.quantity:.0f} / {sd.capacity:.0f}).")
            return
        cost = self.logistics.restock_warehouse_category_cost(cp_id, category)
        budget = self.game.blue.budget if self.game else 0
        base_name = self.base_filter_combo.currentText()
        reply = QMessageBox.question(
            self, f"Restock {category.value.title()}",
            f"Restock {category.value} at {base_name} to full capacity?\n\n"
            f"  Current:  {sd.quantity:.0f} / {sd.capacity:.0f}\n"
            f"  Deficit:  {deficit:.0f} units\n"
            f"  Cost:     ${cost:.2f}M\n\n"
            f"Current budget: ${budget:.1f}M",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if budget < cost:
            QMessageBox.warning(self, "Insufficient funds",
                f"Cannot afford restock.\nCost: ${cost:.2f}M  Budget: ${budget:.1f}M")
            return
        self.logistics.restock_warehouse_category(cp_id, category)
        self.game.blue.adjust_budget(-cost)
        self.refresh()
        self.status_label.setText(
            f"Restocked {category.value} at {base_name} — "
            f"cost ${cost:.2f}M. "
            f"Remaining budget: ${self.game.blue.budget:.1f}M"
        )

    def _on_restock(self) -> None:
        cp_id = self.base_filter_combo.currentData()
        if cp_id == -1 or not self.logistics.is_main_base(cp_id):
            QMessageBox.warning(self, "Main base only",
                "Restock is only available at the designated main base.\n"
                "Set a main base in the Main Base tab first.")
            return
        cost = self.logistics.restock_warehouse_cost(cp_id)
        if cost <= 0:
            QMessageBox.information(self, "Already full", "Warehouse is already at capacity.")
            return
        budget = self.game.blue.budget if self.game else 0
        base_name = self.base_filter_combo.currentText()
        reply = QMessageBox.question(
            self, "Confirm Full Restock",
            f"Restock ALL categories at {base_name} to full capacity?\n\n"
            f"Total cost: ${cost:.1f}M  (rate: $0.05M per unit deficit)\n"
            f"Current budget: ${budget:.1f}M",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if budget < cost:
            QMessageBox.warning(self, "Insufficient funds",
                f"Cannot afford restock.\nCost: ${cost:.1f}M  Budget: ${budget:.1f}M")
            return
        self.logistics.restock_warehouse(cp_id)
        self.game.blue.adjust_budget(-cost)
        self.refresh()
        self.status_label.setText(
            f"Restocked all categories at {base_name} — cost ${cost:.1f}M. "
            f"Remaining budget: ${self.game.blue.budget:.1f}M"
        )

    def _on_export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Warehouse Stock CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            rows = export_warehouse_csv(self.logistics, path)
            self.status_label.setText(f"Exported {rows} bases to: {path}")
            QMessageBox.information(self, "Export successful",
                f"Exported {rows} bases.\n\nColumns: {', '.join(WAREHOUSE_CSV_COLUMNS)}")
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
            QMessageBox.critical(self, "Import failed - wrong format", str(e))
        except Exception as e:
            logger.exception("Warehouse CSV import failed")
            QMessageBox.critical(self, "Import failed", str(e))
