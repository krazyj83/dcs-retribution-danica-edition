
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List

from game.logistics.custom_airdrop import CustomAirdropTarget, create_custom_airdrop_target


# ======================================================================
# Drop Zones
# ======================================================================

class DropZoneType(Enum):
    TROOP = "troop"
    CARGO = "cargo"


@dataclass
class DropZone:
    name: str
    dz_type: DropZoneType
    lat: float
    lon: float
    cp_id: int
    coalition: str
    cp_name: str = ""
    radius_m: float = 500.0
    active: bool = True
    notes: str = ""
    dz_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ======================================================================
# Warehouses
# ======================================================================

class WarehouseCategory(Enum):
    FUEL = "fuel"
    AMMUNITION = "ammunition"
    SUPPLIES = "supplies"
    TROOPS = "troops"


@dataclass
class StockItem:
    quantity: float = 0.0
    capacity: float = 1000.0


@dataclass
class Warehouse:
    cp_id: int
    cp_name: str
    stock: Dict[WarehouseCategory, StockItem] = field(default_factory=dict)

    def __post_init__(self):
        for cat in WarehouseCategory:
            if cat not in self.stock:
                self.stock[cat] = StockItem(quantity=500.0, capacity=1000.0)

    def export_to(self, other: Warehouse, category: WarehouseCategory, amount: float) -> float:
        available = self.stock[category].quantity
        space = other.stock[category].capacity - other.stock[category].quantity
        transferred = min(amount, available, space)
        self.stock[category].quantity -= transferred
        other.stock[category].quantity += transferred
        return transferred


# ======================================================================
# Transfers
# ======================================================================

class TransferStatus(Enum):
    PLANNED = "planned"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class LogisticsTransfer:
    transfer_id: str
    source_cp_id: int
    dest_cp_id: int
    dz_id: str
    category: WarehouseCategory
    quantity: float
    aircraft_type: str
    turn_planned: int
    notes: str = ""
    status: TransferStatus = TransferStatus.PLANNED
    delivered: Optional[float] = None


# ======================================================================
# Logistics Manager
# ======================================================================

class LogisticsManager:
    def __init__(self):
        self._drop_zones: Dict[str, DropZone] = {}
        self._warehouses: Dict[int, Warehouse] = {}
        self._transfers: Dict[str, LogisticsTransfer] = {}

    # --- Drop zones ---

    def add_drop_zone(self, dz: DropZone) -> None:
        self._drop_zones[dz.dz_id] = dz

    def remove_drop_zone(self, dz_id: str) -> None:
        self._drop_zones.pop(dz_id, None)
        for t in list(self._transfers.values()):
            if t.dz_id == dz_id and t.status == TransferStatus.PLANNED:
                t.status = TransferStatus.FAILED

    def get_drop_zone(self, dz_id: str) -> Optional[DropZone]:
        return self._drop_zones.get(dz_id)

    def active_drop_zones(self, coalition: str) -> List[DropZone]:
        return [dz for dz in self._drop_zones.values() if dz.coalition == coalition]

    def drop_zones_for_cp(self, cp_id: int) -> List[DropZone]:
        return [dz for dz in self._drop_zones.values() if dz.cp_id == cp_id]

    # --- Warehouses ---

    def get_warehouse(self, cp_id: int) -> Optional[Warehouse]:
        return self._warehouses.get(cp_id)

    def add_warehouse(self, warehouse: Warehouse) -> None:
        self._warehouses[warehouse.cp_id] = warehouse

    def warehouses_for_coalition(self, coalition: str) -> List[Warehouse]:
        return list(self._warehouses.values())

    # --- Transfers ---

    def schedule_transfer(
        self,
        source_cp_id: int,
        dest_cp_id: int,
        dz_id: str,
        category: WarehouseCategory,
        quantity: float,
        aircraft_type: str,
        turn: int,
        notes: str = "",
    ) -> Optional[LogisticsTransfer]:
        src = self._warehouses.get(source_cp_id)
        if src is None or src.stock[category].quantity < quantity:
            return None
        src.stock[category].quantity -= quantity
        transfer = LogisticsTransfer(
            transfer_id=str(uuid.uuid4()),
            source_cp_id=source_cp_id,
            dest_cp_id=dest_cp_id,
            dz_id=dz_id,
            category=category,
            quantity=quantity,
            aircraft_type=aircraft_type,
            turn_planned=turn,
            notes=notes,
        )
        self._transfers[transfer.transfer_id] = transfer
        return transfer

    def cancel_transfer(self, transfer_id: str) -> bool:
        t = self._transfers.get(transfer_id)
        if t is None or t.status != TransferStatus.PLANNED:
            return False
        src = self._warehouses.get(t.source_cp_id)
        if src:
            src.stock[t.category].quantity += t.quantity
        t.status = TransferStatus.FAILED
        return True


__all__ = [
    "DropZone",
    "DropZoneType",
    "Warehouse",
    "WarehouseCategory",
    "StockItem",
    "LogisticsManager",
    "LogisticsTransfer",
    "TransferStatus",
    "CustomAirdropTarget",
    "create_custom_airdrop_target",
]
