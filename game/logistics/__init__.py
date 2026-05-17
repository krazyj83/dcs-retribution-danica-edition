from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, TYPE_CHECKING

from game.logistics.custom_airdrop import CustomAirdropTarget, create_custom_airdrop_target

if TYPE_CHECKING:
    from game import Game


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
# Warehouses — broad supply categories
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


# ======================================================================
# Weapon / equipment inventory — detailed per-base weapon stocks
# ======================================================================

@dataclass
class WeaponStockItem:
    """Tracks quantity of a specific weapon or piece of equipment at a base."""
    name: str           # Human-readable name e.g. "AIM-120C"
    clsid: str          # DCS CLSID or unit variant_id for ground equipment
    category: str       # "Air-to-Air", "Air-to-Ground", "Bomb", "Ground Unit", etc.
    quantity: int = 0
    capacity: int = 50


@dataclass
class WeaponInventory:
    """Full weapon and equipment inventory for one base."""
    cp_id: int
    cp_name: str
    # keyed by clsid/variant_id
    items: Dict[str, WeaponStockItem] = field(default_factory=dict)

    def add_item(self, clsid: str, name: str, category: str, quantity: int = 10) -> None:
        if clsid in self.items:
            self.items[clsid].quantity += quantity
        else:
            self.items[clsid] = WeaponStockItem(
                name=name,
                clsid=clsid,
                category=category,
                quantity=quantity,
            )

    def zero_all(self) -> None:
        """Set all quantities to zero (used on base capture)."""
        for item in self.items.values():
            item.quantity = 0

    def items_by_category(self) -> Dict[str, List[WeaponStockItem]]:
        result: Dict[str, List[WeaponStockItem]] = {}
        for item in self.items.values():
            result.setdefault(item.category, []).append(item)
        for cat_items in result.values():
            cat_items.sort(key=lambda i: i.name)
        return dict(sorted(result.items()))


def build_weapon_inventory(cp, game: "Game") -> WeaponInventory:
    """
    Build a WeaponInventory for a control point by inspecting:
    1. Squadrons based there — their aircraft pylons/allowed weapons
    2. Ground units at the base — from cp.base.armor
    """
    inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)

    # --- Aircraft weapons from squadrons ---
    try:
        from game.data.weapons import Pylon
        for coalition in [game.blue, game.red]:
            try:
                for aircraft_type, squadrons in coalition.air_wing.squadrons.items():
                    for sq in squadrons:
                        if not hasattr(sq, "location") or sq.location is None:
                            continue
                        if sq.location.id != cp.id:
                            continue
                        # Get all weapons this aircraft can carry
                        try:
                            for pylon in Pylon.iter_pylons(aircraft_type):
                                for weapon in pylon.allowed:
                                    try:
                                        w_name = weapon.name
                                        w_clsid = weapon.clsid
                                        # Categorise by name heuristics
                                        cat = _weapon_category(w_name)
                                        inv.add_item(w_clsid, w_name, cat, quantity=5)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    # --- Ground units from base.armor ---
    try:
        if hasattr(cp, "base") and hasattr(cp.base, "armor"):
            for unit_type, count in cp.base.armor.items():
                if count <= 0:
                    continue
                try:
                    name = getattr(unit_type, "name", str(unit_type))
                    vid  = getattr(unit_type, "variant_id", str(unit_type))
                    price = getattr(unit_type, "price", 0)
                    cat = _ground_unit_category(name)
                    inv.add_item(vid, f"{name} (${price}M)", cat, quantity=count)
                except Exception:
                    pass
    except Exception:
        pass

    return inv


def _weapon_category(name: str) -> str:
    """Heuristic categorisation of a weapon by name."""
    n = name.upper()
    if any(x in n for x in ["AIM-", "R-", "AA-", "MICA", "AMRAAM", "SIDEWINDER",
                              "SPARROW", "ARCHER", "ATOLL", "APHID", "ALAMO"]):
        return "Air-to-Air"
    if any(x in n for x in ["AGM-", "KH-", "Kh-", "AS-", "MAVERICK", "HARM",
                              "HELLFIRE", "PENGUIN", "EXOCET", "HARPOON"]):
        return "Air-to-Ground Missile"
    if any(x in n for x in ["GBU-", "JDAM", "PAVEWAY", "LGB", "MK-8", "MK-8",
                              "FAB-", "KAB-", "BETAB", "OFAB"]):
        return "Bomb"
    if any(x in n for x in ["ROCKET", "S-5", "S-8", "S-13", "S-24", "ZUNI",
                              "HYDRA", "FFAR"]):
        return "Rocket"
    if any(x in n for x in ["DROP TANK", "FUEL TANK", "PTB-"]):
        return "Fuel Tank"
    if any(x in n for x in ["POD", "LITENING", "LANTIRN", "FLIR", "SNIPER",
                              "TARGETING", "ECM", "JAMMER"]):
        return "Pod"
    if any(x in n for x in ["GUN", "CANNON", "GSH", "M61", "GUNPOD"]):
        return "Gun / Cannon"
    if any(x in n for x in ["TORPEDO", "ASM", "ANTI-SHIP"]):
        return "Anti-Ship"
    return "Other"


def _ground_unit_category(name: str) -> str:
    n = name.upper()
    if any(x in n for x in ["TANK", "T-", "M1", "LEOPARD", "CHALLENGER",
                              "ABRAMS", "LECLERC", "TYPE"]):
        return "Armour"
    if any(x in n for x in ["SAM", "SA-", "S-300", "S-400", "PATRIOT", "HAWK",
                              "ROLAND", "TUNGUSKA", "SHILKA", "ZSU", "GEPARD",
                              "LINEBACKER", "AVENGER", "MANPAD"]):
        return "Air Defence"
    if any(x in n for x in ["IFV", "APC", "BTR", "BMP", "BRADLEY", "WARRIOR",
                              "MARDER", "STRYKER"]):
        return "Infantry Fighting Vehicle"
    if any(x in n for x in ["ARTILLERY", "HOWITZER", "MLRS", "BM-", "M109",
                              "MSTA", "CAESAR", "D-30", "GRAD"]):
        return "Artillery"
    if any(x in n for x in ["TRUCK", "UAZ", "HUMVEE", "HMMWV", "TRANSPORT",
                              "SUPPLY"]):
        return "Support Vehicle"
    if any(x in n for x in ["RADAR", "EWR", "AWACS", "COMMAND"]):
        return "Radar / Command"
    return "Other Ground"


# ======================================================================
# Warehouse — broad supply categories
# ======================================================================

@dataclass
class Warehouse:
    cp_id: int
    cp_name: str
    stock: Dict[WarehouseCategory, StockItem] = field(default_factory=dict)

    def __post_init__(self):
        for cat in WarehouseCategory:
            if cat not in self.stock:
                self.stock[cat] = StockItem(quantity=500.0, capacity=1000.0)

    def export_to(self, other: "Warehouse", category: WarehouseCategory, amount: float) -> float:
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
        self._weapon_inventories: Dict[int, WeaponInventory] = {}
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
        return list(self._drop_zones.values())

    def drop_zones_for_cp(self, cp_id: int) -> List[DropZone]:
        return [dz for dz in self._drop_zones.values() if dz.cp_id == cp_id]

    # --- Warehouses ---

    def get_warehouse(self, cp_id: int) -> Optional[Warehouse]:
        return self._warehouses.get(cp_id)

    def add_warehouse(self, warehouse: Warehouse) -> None:
        self._warehouses[warehouse.cp_id] = warehouse

    def warehouses_for_coalition(self, coalition: str) -> List[Warehouse]:
        return list(self._warehouses.values())

    # --- Weapon inventories ---

    def get_weapon_inventory(self, cp_id: int) -> Optional[WeaponInventory]:
        return self._weapon_inventories.get(cp_id)

    def set_weapon_inventory(self, inv: WeaponInventory) -> None:
        self._weapon_inventories[inv.cp_id] = inv

    def sync_weapon_inventories(self, game: "Game") -> None:
        """Rebuild weapon inventories for all blue bases from current game state."""
        try:
            for cp in game.theater.player_points():
                inv = build_weapon_inventory(cp, game)
                self._weapon_inventories[cp.id] = inv
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to sync weapon inventories: {e}"
            )

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
    "WeaponStockItem",
    "WeaponInventory",
    "LogisticsManager",
    "LogisticsTransfer",
    "TransferStatus",
    "build_weapon_inventory",
    "CustomAirdropTarget",
    "create_custom_airdrop_target",
]
