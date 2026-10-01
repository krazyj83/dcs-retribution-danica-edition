from __future__ import annotations

import logging
import uuid
from uuid import UUID
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List, Tuple, TYPE_CHECKING

from game.logistics.custom_airdrop import (
    CustomAirdropTarget,
    create_custom_airdrop_target,
)

if TYPE_CHECKING:
    from dcs.mission import Mission

    from game import Game
    from game.debriefing import Debriefing
    from game.theater import ControlPoint
    from game.squadrons import Squadron

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
    cp_id: Optional[UUID]
    coalition: str
    cp_name: str = ""
    radius_m: float = 500.0
    active: bool = True
    notes: str = ""
    dz_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ======================================================================
# Warehouses - broad supply categories
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

    @property
    def level(self) -> float:
        """Supply level as a fraction 0.0-1.0."""
        from game.logistics.levels import level

        return level(self.quantity, self.capacity)

    @property
    def needs_resupply(self) -> bool:
        """True below the resupply threshold (levels.LOW_LEVEL)."""
        from game.logistics.levels import LOW_LEVEL

        return self.level < LOW_LEVEL

    def apply_delivery(self, amount: float) -> None:
        """Add stock from a completed logistic flight. Clamps to capacity."""
        self.quantity = min(self.capacity, self.quantity + amount)

    def apply_consumption(self, amount: float) -> None:
        """Subtract per-turn consumption. Clamps to zero, never negative."""
        self.quantity = max(0.0, self.quantity - amount)


# ======================================================================
# Weapon / equipment inventory - detailed per-base weapon stocks
# ======================================================================


@dataclass
class WeaponStockItem:
    """Tracks quantity of a specific weapon or piece of equipment at a base."""

    name: str  # Human-readable name e.g. "AIM-120C"
    clsid: str  # DCS CLSID or unit variant_id for ground equipment
    category: str  # "Air-to-Air", "Air-to-Ground", "Bomb", "Ground Unit", etc.
    quantity: int = 0
    capacity: int = 250


@dataclass
class WeaponInventory:
    """Full weapon and equipment inventory for one base."""

    cp_id: UUID
    cp_name: str
    items: Dict[str, WeaponStockItem] = field(default_factory=dict)

    def add_item(
        self, clsid: str, name: str, category: str, quantity: int = 10
    ) -> None:
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


def build_weapon_inventory(cp: "ControlPoint", game: "Game") -> WeaponInventory:
    """
    Build a WeaponInventory for a control point by inspecting:
    1. Squadrons based there - their aircraft pylons/allowed weapons
    2. Ground units at the base - from cp.base.armor
    """
    inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)

    try:
        from game.data.weapons import Pylon

        # Weapon stores are BLUEFOR's; REDFOR sorties use the ammunition stock.
        for coalition in [game.blue]:
            try:
                for aircraft_type, squadrons in coalition.air_wing.squadrons.items():
                    for sq in squadrons:
                        if not hasattr(sq, "location") or sq.location is None:
                            continue
                        if sq.location.id != cp.id:
                            continue
                        try:
                            for pylon in Pylon.iter_pylons(aircraft_type):
                                for weapon in pylon.allowed:
                                    try:
                                        inv.add_item(
                                            weapon.clsid,
                                            weapon.name,
                                            _weapon_category(weapon.name),
                                            quantity=5,
                                        )
                                    except Exception:
                                        pass
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    try:
        if hasattr(cp, "base") and hasattr(cp.base, "armor"):
            for unit_type, count in cp.base.armor.items():
                if count <= 0:
                    continue
                try:
                    name = getattr(unit_type, "name", str(unit_type))
                    vid = getattr(unit_type, "variant_id", str(unit_type))
                    price = getattr(unit_type, "price", 0)
                    inv.add_item(
                        vid,
                        f"{name} (${price}M)",
                        _ground_unit_category(name),
                        quantity=count,
                    )
                except Exception:
                    pass
    except Exception:
        pass

    return inv


#: Soviet air-to-air missile names ("R-60M", "2 x R-73"), but not the "R-" in
#: BR-250, LR-25 or TER-9.
_SOVIET_AAM = re.compile(r"(^|[^A-Z0-9])R-\d")


def _weapon_category(name: str) -> str:
    n = name.upper()
    if _SOVIET_AAM.search(n) or any(
        x in n
        for x in [
            "AIM-",
            "AA-",
            "MICA",
            "AMRAAM",
            "SIDEWINDER",
            "SPARROW",
            "ARCHER",
            "ATOLL",
            "APHID",
            "ALAMO",
        ]
    ):
        return "Air-to-Air"
    if any(
        x in n
        for x in [
            "AGM-",
            "KH-",
            "AS-",
            "MAVERICK",
            "HARM",
            "HELLFIRE",
            "PENGUIN",
            "EXOCET",
            "HARPOON",
        ]
    ):
        return "Air-to-Ground Missile"
    if any(
        x in n
        for x in [
            "GBU-",
            "JDAM",
            "PAVEWAY",
            "LGB",
            "MK-8",
            "FAB-",
            "KAB-",
            "BETAB",
            "OFAB",
            "BR-2",
            "BR-5",
        ]
    ):
        return "Bomb"
    if any(
        x in n
        for x in [
            "ROCKET",
            "RKTS",
            "S-5",
            "S-8",
            "S-13",
            "S-24",
            "ZUNI",
            "HYDRA",
            "FFAR",
        ]
    ):
        return "Rocket"
    if any(x in n for x in ["DROP TANK", "FUEL TANK", "PTB-"]):
        return "Fuel Tank"
    if any(
        x in n
        for x in [
            "POD",
            "LITENING",
            "LANTIRN",
            "FLIR",
            "SNIPER",
            "TARGETING",
            "ECM",
            "JAMMER",
        ]
    ):
        return "Pod"
    if any(x in n for x in ["GUN", "CANNON", "GSH", "M61", "GUNPOD"]):
        return "Gun / Cannon"
    if any(x in n for x in ["TORPEDO", "ASM", "ANTI-SHIP"]):
        return "Anti-Ship"
    return "Other"


def _ground_unit_category(name: str) -> str:
    n = name.upper()
    if any(
        x in n
        for x in [
            "TANK",
            "T-",
            "M1",
            "LEOPARD",
            "CHALLENGER",
            "ABRAMS",
            "LECLERC",
            "TYPE",
        ]
    ):
        return "Armour"
    if any(
        x in n
        for x in [
            "SAM",
            "SA-",
            "S-300",
            "S-400",
            "PATRIOT",
            "HAWK",
            "ROLAND",
            "TUNGUSKA",
            "SHILKA",
            "ZSU",
            "GEPARD",
            "LINEBACKER",
            "AVENGER",
            "MANPAD",
        ]
    ):
        return "Air Defence"
    if any(
        x in n
        for x in ["IFV", "APC", "BTR", "BMP", "BRADLEY", "WARRIOR", "MARDER", "STRYKER"]
    ):
        return "Infantry Fighting Vehicle"
    if any(
        x in n
        for x in [
            "ARTILLERY",
            "HOWITZER",
            "MLRS",
            "BM-",
            "M109",
            "MSTA",
            "CAESAR",
            "D-30",
            "GRAD",
        ]
    ):
        return "Artillery"
    if any(x in n for x in ["TRUCK", "UAZ", "HUMVEE", "HMMWV", "TRANSPORT", "SUPPLY"]):
        return "Support Vehicle"
    if any(x in n for x in ["RADAR", "EWR", "AWACS", "COMMAND"]):
        return "Radar / Command"
    return "Other Ground"


# ======================================================================
# Warehouse - broad supply categories
# ======================================================================


@dataclass
class Warehouse:
    cp_id: UUID
    cp_name: str
    stock: Dict[WarehouseCategory, StockItem] = field(default_factory=dict)
    #: Fuel the base's sorties used in the last mission (see logistics/fuel.py).
    #: Class-level default keeps warehouses pickled before this field loadable.
    fuel_used_last_mission: float = 0.0
    #: Owner of the base: "blue" or "red" (logistics/redfor.py keeps it in
    #: step with captures). Class default: older saves only had blue ones.
    coalition: str = "blue"
    #: Ammunition REDFOR sorties took in the last mission (logistics/redfor.py).
    ammo_used_last_mission: float = 0.0

    def __post_init__(self) -> None:
        for cat in WarehouseCategory:
            if cat not in self.stock:
                self.stock[cat] = StockItem(quantity=500.0, capacity=1000.0)

    def export_to(
        self, other: "Warehouse", category: WarehouseCategory, amount: float
    ) -> float:
        available = self.stock[category].quantity
        space = other.stock[category].capacity - other.stock[category].quantity
        transferred = min(amount, available, space)
        self.stock[category].quantity -= transferred
        other.stock[category].quantity += transferred
        return transferred


#: Price ($M) of one weapon or round when restocking weapon stores.
WEAPON_RESTOCK_COST = 0.01
#: Weapon inventory categories restocked at the ground unit's own price.
_GROUND_UNIT_RESTOCK_CATEGORIES = frozenset(
    {
        "Armour",
        "Air Defence",
        "Infantry Fighting Vehicle",
        "Artillery",
        "Support Vehicle",
        "Radar / Command",
        "Other Ground",
    }
)


def _ground_unit_prices() -> Dict[str, float]:
    from game.dcs.groundunittype import GroundUnitType

    return {
        str(getattr(unit, "variant_id", "")): float(unit.price)
        for unit in GroundUnitType._by_name.values()
    }


def item_restock_cost(item: WeaponStockItem) -> float:
    """Cost ($M) to restock one weapon inventory item to capacity.

    Weapons and rounds: WEAPON_RESTOCK_COST each. Ground units: their
    procurement price each.
    """
    deficit = item.capacity - item.quantity
    if deficit <= 0:
        return 0.0
    price = WEAPON_RESTOCK_COST
    if item.category in _GROUND_UNIT_RESTOCK_CATEGORIES:
        try:
            price = _ground_unit_prices().get(item.clsid, WEAPON_RESTOCK_COST)
        except Exception:
            price = WEAPON_RESTOCK_COST
    return round(deficit * price, 1)


#: BLUEFOR bases' fuel tank farm: a busy airfield flies 600-800 fuel worth of
#: sorties a turn, so 1000 ran dry within a turn or two.
BLUE_FUEL_CAPACITY = 2000.0


#: REDFOR warehouses: fuel, ammunition and supplies (logistics/redfor.py).
RED_CAPACITY = 2000.0
#: Everything else.
DEFAULT_CAPACITY = 1000.0


def keeps_warehouse(cp: Any) -> bool:
    """Does this base keep warehouse stock? Not ships (supplied at sea) and
    not off-map spawns."""
    from game.theater.controlpoint import OffMapSpawn

    return not isinstance(cp, OffMapSpawn) and not getattr(cp, "is_fleet", False)


def _capacities(red: bool) -> Dict[WarehouseCategory, float]:
    if red:
        return {
            WarehouseCategory.FUEL: RED_CAPACITY,
            WarehouseCategory.AMMUNITION: RED_CAPACITY,
            WarehouseCategory.SUPPLIES: RED_CAPACITY,
            WarehouseCategory.TROOPS: DEFAULT_CAPACITY,
        }
    return {
        WarehouseCategory.FUEL: BLUE_FUEL_CAPACITY,
        WarehouseCategory.AMMUNITION: DEFAULT_CAPACITY,
        WarehouseCategory.SUPPLIES: DEFAULT_CAPACITY,
        WarehouseCategory.TROOPS: DEFAULT_CAPACITY,
    }


def new_base_warehouse(cp: Any, side: Any = None) -> Warehouse:
    """The warehouse a base gets the first time it needs one.

    The only place warehouses are made for bases. ``side`` defaults to the
    base's owner. BLUEFOR: default stock, fuel BLUE_FUEL_CAPACITY and full.
    REDFOR: fuel, ammunition and supplies RED_CAPACITY and full.
    """
    owner = side if side is not None else getattr(cp, "captured", None)
    red = bool(getattr(owner, "is_red", False))
    warehouse = Warehouse(cp_id=cp.id, cp_name=cp.name)
    warehouse.coalition = "red" if red else "blue"
    for category, capacity in _capacities(red).items():
        item = warehouse.stock[category]
        item.capacity = capacity
        if category is WarehouseCategory.FUEL or red:
            item.quantity = capacity
    return warehouse


def fit_to_owner(warehouse: Warehouse, side: Any) -> None:
    """A base changed hands (or an older save): the new owner's capacities.

    Stock above a smaller capacity is lost; nothing is added.
    """
    red = bool(getattr(side, "is_red", False))
    warehouse.coalition = "red" if red else "blue"
    for category, capacity in _capacities(red).items():
        item = warehouse.stock[category]
        item.capacity = capacity
        item.quantity = min(item.quantity, capacity)


def upgrade_blue_fuel_capacity(warehouse: Warehouse) -> None:
    """Saves from before BLUE_FUEL_CAPACITY: bigger tanks, same fuel in them."""
    fuel = warehouse.stock[WarehouseCategory.FUEL]
    if fuel.capacity < BLUE_FUEL_CAPACITY:
        fuel.capacity = BLUE_FUEL_CAPACITY


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
    source_cp_id: UUID
    dest_cp_id: UUID
    dz_id: str
    category: WarehouseCategory
    quantity: float
    aircraft_type: str
    turn_planned: int
    notes: str = ""
    status: TransferStatus = TransferStatus.PLANNED
    delivered: Optional[float] = None
    #: Squadron the player picked to fly it (BLUEFOR supplies are player-flown).
    #: Class-level default keeps transfers pickled before this field loadable.
    squadron: Optional["Squadron"] = None
    #: Weapons carried, DCS clsid -> count (weapon transfers). None for the
    #: older category transfers. Class-level defaults keep old saves loadable.
    cargo: Optional[Dict[str, int]] = None
    #: Fuel load the player picked (1.0, 0.5 or 0.25 of full tanks).
    fuel_fraction: float = 1.0

    @property
    def cargo_label(self) -> str:
        """What the transfer carries, for logs and the transfer table."""
        if self.cargo is not None:
            from game.logistics.cargo import manifest_summary

            return manifest_summary(self.cargo) or "no cargo"
        return f"{self.quantity:.0f} {self.category.value}"

    def mark_in_flight(self) -> None:
        """Called by on_turn_end when the transfer's flight is in the ATO.
        Raises ValueError if the transfer isn't
        in the PLANNED state (e.g. it was already marked, or cancelled)."""
        if self.status != TransferStatus.PLANNED:
            raise ValueError(
                f"Cannot mark transfer {self.transfer_id} in_flight from "
                f"status {self.status.value!r} (expected 'planned')"
            )
        self.status = TransferStatus.IN_FLIGHT

    def mark_delivered(self, amount: Optional[float] = None) -> None:
        """Called by debrief_hook.py once the mission ends successfully."""
        self.status = TransferStatus.DELIVERED
        self.delivered = amount if amount is not None else self.quantity

    def mark_failed(self) -> None:
        """Called when the flight is lost/aborted before delivering."""
        self.status = TransferStatus.FAILED


# ======================================================================
# Logistics Manager
# ======================================================================


class LogisticsManager:

    #: Fraction of every warehouse category lost each turn (handling, spoilage).
    ATTRITION_PER_TURN = 0.01
    #: Delivered and failed transfers stay in the Transfers list this many
    #: turns, then are dropped so saves don't keep them forever.
    FINISHED_TRANSFER_TURNS = 5

    def __init__(self) -> None:
        self._drop_zones: Dict[str, DropZone] = {}
        self._warehouses: Dict[UUID, Warehouse] = {}
        self._weapon_inventories: Dict[UUID, WeaponInventory] = {}
        self._transfers: Dict[str, LogisticsTransfer] = {}
        self._main_base_cp_id: Optional[UUID] = None
        #: Last turn attrition was applied, so regenerating a mission doesn't
        #: apply it twice.
        self._last_attrition_turn: Optional[int] = None
        #: Stock per base, turn by turn (see logistics/history.py).
        self._history: Dict[UUID, List[Any]] = {}
        #: Per-turn activity, turn -> TurnStats (logistics/campaign_stats.py).
        self._turn_stats: Dict[int, Any] = {}
        #: Recon reports on REDFOR bases (see logistics/intel.py).
        self._red_intel: Dict[UUID, Any] = {}
        #: Turn reports by turn (see logistics/turn_report.py).
        self._turn_reports: Dict[int, Any] = {}
        #: Lines for the debrief window (add_debrief_log / pop_debrief_log).
        self._debrief_log: List[str] = []
        #: REDFOR packages grounded this turn, by base (logistics/redfor.py).
        self._red_grounded: Dict[str, Any] = {}
        #: Last turn REDFOR was resupplied, so it happens once per turn.
        self._red_resupply_turn: Optional[int] = None

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """Saves from before a field existed get its default: the one place
        that keeps old campaigns loading as fields are added."""
        defaults = LogisticsManager().__dict__
        for key, value in defaults.items():
            state.setdefault(key, value)
        self.__dict__.update(state)

    # ── Drop zones ─────────────────────────────────────────────────────

    def add_drop_zone(self, dz: DropZone) -> None:
        self._drop_zones[dz.dz_id] = dz

    def remove_drop_zone(self, dz_id: str, game: Optional["Game"] = None) -> None:
        """Remove a drop zone and cancel the planned transfers to it.

        Their cargo goes back to stock (cancel_transfer); with the game given,
        their LOGISTIC flights are removed from the ATO too.
        """
        self._drop_zones.pop(dz_id, None)
        for t in list(self._transfers.values()):
            if t.dz_id == dz_id and t.status == TransferStatus.PLANNED:
                self.cancel_transfer(t.transfer_id)
                if game is not None:
                    from game.logistics.transfer_flights import (
                        remove_transfer_flight,
                    )

                    try:
                        remove_transfer_flight(game, t.transfer_id)
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Could not remove the flight of a cancelled transfer"
                        )

    def get_drop_zone(self, dz_id: str) -> Optional[DropZone]:
        return self._drop_zones.get(dz_id)

    def drop_zones_for_cp(self, cp_id: UUID) -> List[DropZone]:
        return [dz for dz in self._drop_zones.values() if dz.cp_id == cp_id]

    def inject_into_mission(self, mission: "Mission") -> None:
        """
        Create a real DCS trigger zone for every active drop zone, so the
        cargo script can locate them at runtime.

        This method didn't exist before — missiongenerator.py has been
        calling game.logistics.inject_into_mission(self.mission) since it
        was written, but nothing defined it, so every mission generation
        raised AttributeError here (silently caught by the try/except
        around the call site) and no drop zone was ever actually written
        into the .miz file.

        Uses the same mission.triggers.add_triggerzone() API that
        LogisticsGenerator (game/missiongenerator/logisticsgenerator.py)
        already uses for CTLD pickup/dropoff zones, so zone creation is
        consistent with the rest of the codebase.
        """
        import logging
        from dcs.mapping import LatLng, Point

        logger = logging.getLogger(__name__)
        created = 0

        for dz in self._drop_zones.values():
            if not dz.active:
                continue
            try:
                position = Point.from_latlng(LatLng(dz.lat, dz.lon), mission.terrain)
            except Exception:
                logger.exception(
                    "inject_into_mission: failed to convert drop zone "
                    "'%s' (%s) to a mission position — skipped",
                    dz.name,
                    dz.dz_id,
                )
                continue

            # Zone name is prefixed and includes a short id so it's both
            # human-readable in the DCS Mission Editor and unique even if
            # two drop zones share a name.
            zone_name = f"DZ_{dz.dz_id[:8]}_{dz.name}"
            try:
                mission.triggers.add_triggerzone(
                    position, dz.radius_m, False, zone_name
                )
                created += 1
            except Exception:
                logger.exception(
                    "inject_into_mission: failed to create trigger zone "
                    "for drop zone '%s' (%s) — skipped",
                    dz.name,
                    dz.dz_id,
                )

        logger.info(
            "inject_into_mission: created %d of %d drop zone trigger zone(s)",
            created,
            len(self._drop_zones),
        )

    # ── Warehouses ─────────────────────────────────────────────────────

    def get_warehouse(self, cp_id: UUID) -> Optional[Warehouse]:
        return self._warehouses.get(cp_id)

    def add_warehouse(self, warehouse: Warehouse) -> None:
        self._warehouses[warehouse.cp_id] = warehouse

    def warehouses_for_coalition(self, coalition: str) -> List[Warehouse]:
        return [
            w
            for w in self._warehouses.values()
            if getattr(w, "coalition", "blue") == coalition
        ]

    # ── Weapon inventories ─────────────────────────────────────────────

    def get_weapon_inventory(self, cp_id: UUID) -> Optional[WeaponInventory]:
        return self._weapon_inventories.get(cp_id)

    def set_weapon_inventory(self, inv: WeaponInventory) -> None:
        self._weapon_inventories[inv.cp_id] = inv

    def sync_weapon_inventories(self, game: "Game") -> None:
        """Refresh weapon inventories for all blue bases from current game state.

        Weapons new to a base are added; weapons already tracked keep their
        quantity and capacity, so stock moved by transfers isn't reset.
        Ground units are always re-read from the garrison.
        """
        from dcs.weapons_data import weapon_ids

        try:
            for cp in game.theater.player_points():
                fresh = build_weapon_inventory(cp, game)
                current = self._weapon_inventories.get(cp.id)
                if current is not None:
                    for clsid, item in current.items.items():
                        if clsid in weapon_ids:
                            if clsid in fresh.items:
                                # Stock is kept; the category follows the rules.
                                item.category = fresh.items[clsid].category
                            fresh.items[clsid] = item
                self._weapon_inventories[cp.id] = fresh
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                f"Failed to sync weapon inventories: {e}"
            )

    # ── Main Base ──────────────────────────────────────────────────────

    @property
    def main_base_cp_id(self) -> Optional[UUID]:
        """The cp_id of the designated main supply base, or None."""
        return self._main_base_cp_id

    def set_main_base(self, cp_id: Optional[UUID]) -> None:
        """Designate a base as the main supply hub (or clear with None)."""
        self._main_base_cp_id = cp_id

    def is_main_base(self, cp_id: UUID) -> bool:
        return self._main_base_cp_id == cp_id

    # ── Restock helpers ────────────────────────────────────────────────

    # Cost rate used by all warehouse restock methods.
    _WAREHOUSE_COST_PER_UNIT = 0.05  # $M per unit of deficit

    def restock_warehouse_cost(self, cp_id: UUID) -> float:
        """Cost ($M) to fully restock ALL warehouse categories to capacity.

        Sums the per-category cost across every WarehouseCategory.
        Rate: $0.05M per unit deficit.
        """
        wh = self.get_warehouse(cp_id)
        if wh is None:
            return 0.0
        total = sum(
            max(0.0, wh.stock[cat].capacity - wh.stock[cat].quantity)
            * self._WAREHOUSE_COST_PER_UNIT
            for cat in WarehouseCategory
        )
        return round(total, 1)

    def restock_warehouse_category_cost(
        self, cp_id: UUID, category: WarehouseCategory
    ) -> float:
        """Cost ($M) to restock a SINGLE warehouse category to capacity.

        Same rate as restock_warehouse_cost() but scoped to one category,
        so the UI can show per-category costs on individual restock buttons.
        Rate: $0.05M per unit deficit.
        """
        wh = self.get_warehouse(cp_id)
        if wh is None:
            return 0.0
        deficit = max(
            0.0,
            wh.stock[category].capacity - wh.stock[category].quantity,
        )
        return round(deficit * self._WAREHOUSE_COST_PER_UNIT, 2)

    def restock_warehouse(self, cp_id: UUID) -> None:
        """Fill ALL warehouse categories to capacity."""
        wh = self.get_warehouse(cp_id)
        if wh is None:
            return
        for cat in WarehouseCategory:
            wh.stock[cat].quantity = wh.stock[cat].capacity

    def restock_warehouse_category(
        self, cp_id: UUID, category: WarehouseCategory
    ) -> None:
        """Fill ONE warehouse category to capacity.

        Called by the per-category restock buttons in WarehouseTab.
        """
        wh = self.get_warehouse(cp_id)
        if wh is None:
            return
        wh.stock[category].quantity = wh.stock[category].capacity

    def restock_inventory_cost(self, cp_id: UUID) -> float:
        """Cost ($M) to refill ALL weapon/equipment inventory to capacity.

        Same prices as one item at a time (item_restock_cost).
        """
        inv = self.get_weapon_inventory(cp_id)
        if inv is None:
            return 0.0
        return round(sum(item_restock_cost(i) for i in inv.items.values()), 1)

    def restock_inventory(self, cp_id: UUID) -> None:
        """Fill ALL weapon/equipment inventory items to capacity."""
        inv = self.get_weapon_inventory(cp_id)
        if inv is None:
            return
        for item in inv.items.values():
            item.quantity = item.capacity

    # ── Transfers ──────────────────────────────────────────────────────

    def schedule_transfer(
        self,
        source_cp_id: UUID,
        dest_cp_id: UUID,
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

    def schedule_weapon_transfer(
        self,
        source_cp_id: UUID,
        dest_cp_id: UUID,
        dz_id: str,
        cargo: Dict[str, int],
        aircraft_type: str,
        turn: int,
        fuel_fraction: float = 1.0,
        notes: str = "",
    ) -> Optional[LogisticsTransfer]:
        """Take the weapons out of the source inventory and create a transfer.

        None (nothing taken) if the source doesn't hold every item in the
        requested quantity.
        """
        cargo = {clsid: int(n) for clsid, n in cargo.items() if n > 0}
        src = self._weapon_inventories.get(source_cp_id)
        if not cargo or src is None:
            return None
        for clsid, count in cargo.items():
            item = src.items.get(clsid)
            if item is None or item.quantity < count:
                return None
        for clsid, count in cargo.items():
            src.items[clsid].quantity -= count
        transfer = LogisticsTransfer(
            transfer_id=str(uuid.uuid4()),
            source_cp_id=source_cp_id,
            dest_cp_id=dest_cp_id,
            dz_id=dz_id,
            category=WarehouseCategory.AMMUNITION,
            quantity=float(sum(cargo.values())),
            aircraft_type=aircraft_type,
            turn_planned=turn,
            notes=notes,
            cargo=cargo,
            fuel_fraction=fuel_fraction,
        )
        self._transfers[transfer.transfer_id] = transfer
        return transfer

    # ── Transfers planned with a flight (mission planner Cargo tab) ─────

    def create_flight_transfer(
        self,
        source_cp_id: UUID,
        dest_cp_id: UUID,
        dz_id: str,
        aircraft_type: str,
        turn: int,
    ) -> LogisticsTransfer:
        """An empty weapon transfer for a LOGISTIC flight; cargo is added later."""
        transfer = LogisticsTransfer(
            transfer_id=str(uuid.uuid4()),
            source_cp_id=source_cp_id,
            dest_cp_id=dest_cp_id,
            dz_id=dz_id,
            category=WarehouseCategory.AMMUNITION,
            quantity=0.0,
            aircraft_type=aircraft_type,
            turn_planned=turn,
            cargo={},
        )
        self._transfers[transfer.transfer_id] = transfer
        return transfer

    def add_cargo(self, transfer: LogisticsTransfer, clsid: str, count: int) -> int:
        """Load weapons from the pickup base's stock. Returns how many were added."""
        if transfer.status is not TransferStatus.PLANNED or transfer.cargo is None:
            return 0
        src = self._weapon_inventories.get(transfer.source_cp_id)
        item = src.items.get(clsid) if src is not None else None
        if item is None:
            return 0
        added = max(0, min(int(count), item.quantity))
        if added:
            item.quantity -= added
            transfer.cargo[clsid] = transfer.cargo.get(clsid, 0) + added
            transfer.quantity = float(sum(transfer.cargo.values()))
        return added

    def remove_cargo(
        self, transfer: LogisticsTransfer, clsid: str, count: Optional[int] = None
    ) -> int:
        """Unload weapons back into the pickup base's stock. Returns how many."""
        if transfer.status is not TransferStatus.PLANNED or not transfer.cargo:
            return 0
        loaded = transfer.cargo.get(clsid, 0)
        removed = loaded if count is None else max(0, min(int(count), loaded))
        if removed:
            self._return_weapons(transfer.source_cp_id, {clsid: removed})
            if loaded - removed:
                transfer.cargo[clsid] = loaded - removed
            else:
                del transfer.cargo[clsid]
            transfer.quantity = float(sum(transfer.cargo.values()))
        return removed

    def change_pickup(self, transfer: LogisticsTransfer, source_cp_id: UUID) -> None:
        """Pick up somewhere else: loaded cargo goes back to the old base."""
        if transfer.status is not TransferStatus.PLANNED:
            return
        if transfer.cargo:
            self._return_weapons(transfer.source_cp_id, transfer.cargo)
        transfer.cargo = {} if transfer.cargo is not None else None
        transfer.quantity = 0.0
        transfer.source_cp_id = source_cp_id

    def _take_weapons(self, cp_id: UUID, cargo: Dict[str, int]) -> None:
        """Remove weapons from a base's stock (never below zero)."""
        inv = self._weapon_inventories.get(cp_id)
        if inv is None:
            return
        for clsid, count in cargo.items():
            item = inv.items.get(clsid)
            if item is not None:
                item.quantity = max(0, item.quantity - count)

    def _put_weapons(self, cp: Any, cargo: Dict[str, int]) -> Dict[str, int]:
        """Add weapons to a base's stock. Returns what didn't fit."""
        from game.logistics.cargo import weapon_name

        inv = self._weapon_inventories.get(cp.id)
        if inv is None:
            inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)
            self._weapon_inventories[cp.id] = inv
        overflow: Dict[str, int] = {}
        for clsid, count in cargo.items():
            item = inv.items.get(clsid)
            if item is None:
                name = weapon_name(clsid)
                inv.add_item(clsid, name, _weapon_category(name), quantity=0)
                item = inv.items[clsid]
            fits = min(count, max(0, item.capacity - item.quantity))
            item.quantity += fits
            if count - fits:
                overflow[clsid] = count - fits
        return overflow

    def _return_weapons(self, cp_id: UUID, cargo: Dict[str, int]) -> None:
        """Put weapons back into a base's inventory (cancel or overflow)."""
        inv = self._weapon_inventories.get(cp_id)
        if inv is None:
            return
        from game.logistics.cargo import weapon_name

        for clsid, count in cargo.items():
            item = inv.items.get(clsid)
            if item is None:
                name = weapon_name(clsid)
                inv.add_item(clsid, name, _weapon_category(name), quantity=count)
            else:
                item.quantity += count

    def _deliver_weapons(
        self, t: LogisticsTransfer, source_cp_id: UUID, dest_cp_id: UUID, dest_name: str
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Add a weapon transfer's cargo to the destination inventory.

        Returns (delivered, overflow). What doesn't fit goes back to the
        source inventory. The destination inventory is created if needed.
        """
        from game.logistics.cargo import weapon_name

        dest = self._weapon_inventories.get(dest_cp_id)
        if dest is None:
            dest = WeaponInventory(cp_id=dest_cp_id, cp_name=dest_name)
            self._weapon_inventories[dest_cp_id] = dest
        src = self._weapon_inventories.get(source_cp_id)
        delivered: Dict[str, int] = {}
        overflow: Dict[str, int] = {}
        for clsid, count in (t.cargo or {}).items():
            item = dest.items.get(clsid)
            if item is None:
                known = src.items.get(clsid) if src is not None else None
                name = known.name if known is not None else weapon_name(clsid)
                category = (
                    known.category if known is not None else _weapon_category(name)
                )
                dest.add_item(clsid, name, category, quantity=0)
                item = dest.items[clsid]
            fits = min(count, max(0, item.capacity - item.quantity))
            item.quantity += fits
            if fits:
                delivered[clsid] = fits
            if count - fits:
                overflow[clsid] = count - fits
        if overflow:
            self._return_weapons(source_cp_id, overflow)
        return delivered, overflow

    # ── Turn hooks (called from game/sim/gameloop.py) ─────────────────

    def on_turn_end(self, game: "Game") -> None:
        """Mission is being generated: transfers with a flight go IN_FLIGHT.

        Also applies once-per-turn warehouse attrition. Called every time the
        mission is (re)generated, so both steps are idempotent within a turn.
        """
        from game.logistics.transfer_flights import flight_for_transfer

        from game.logistics.fuel import unlimited_fuel

        if self._last_attrition_turn != game.turn:
            self._last_attrition_turn = game.turn
            keep_fuel = unlimited_fuel(game)
            for wh in self._warehouses.values():
                if getattr(wh, "coalition", "blue") == "red":
                    # REDFOR stock follows its own model (logistics/redfor.py:
                    # what it uses comes back, scaled by the depots left).
                    continue
                for category, item in wh.stock.items():
                    if keep_fuel and category is WarehouseCategory.FUEL:
                        continue
                    item.apply_consumption(item.quantity * self.ATTRITION_PER_TURN)

        # Stock going into this turn's mission, for the history chart.
        from game.logistics.history import ensure_friendly_warehouses, record_turn
        from game.logistics.redfor import (
            enabled as redfor_enabled,
            ensure_red_warehouses,
            sync_warehouse_sides,
        )

        ensure_friendly_warehouses(game)
        if redfor_enabled(game):
            ensure_red_warehouses(game)
        sync_warehouse_sides(game)
        record_turn(self, game.turn)

        for t in self._transfers.values():
            if t.status is TransferStatus.PLANNED and flight_for_transfer(
                game, t.transfer_id
            ):
                t.mark_in_flight()
        self.prune_finished_transfers(game.turn)

    def prune_finished_transfers(self, turn: int) -> None:
        """Drop delivered and failed transfers planned more than
        FINISHED_TRANSFER_TURNS turns ago."""
        finished = (TransferStatus.DELIVERED, TransferStatus.FAILED)
        oldest = turn - self.FINISHED_TRANSFER_TURNS
        for tid, t in list(self._transfers.items()):
            if t.status in finished and t.turn_planned < oldest:
                del self._transfers[tid]

    def on_state_processed(self, game: "Game", debriefing: "Debriefing") -> List[str]:
        """Settle IN_FLIGHT transfers from the mission results.

        - Every aircraft of the flight lost: FAILED, cargo lost.
        - Source or destination no longer friendly: FAILED, cargo lost.
        - Otherwise DELIVERED: what fits goes into the destination warehouse,
          the overflow returns to the source warehouse.
        - Flight no longer in the ATO: back to PLANNED, flown next turn.

        Runs after results are committed (captures applied) and before
        Game.pass_turn() clears the ATO. Returns human-readable log lines.
        """
        from game.logistics.fuel import use_fuel_for_sorties
        from game.logistics.transfer_flights import control_point, flight_for_transfer
        from game.theater.player import Player

        log: List[str] = []
        from game.logistics import turn_report

        from game.logistics.campaign_stats import StatsRecorder

        report = turn_report.start_report(game, debriefing, list(self._debrief_log))
        stats = StatsRecorder(self, game.turn)
        # Depot and SAM damage first: REDFOR resupply, repairs and next turn's
        # planning (all at the end of the turn) must see it.
        try:
            from game.logistics.debrief_hook import apply_damage

            log.extend(stats.measure("damage", lambda: apply_damage(debriefing)))
        except Exception:
            logging.getLogger(__name__).exception("Depot/SAM damage failed")
        try:
            fuel_log = stats.measure(
                "fuel", lambda: use_fuel_for_sorties(game, debriefing)
            )
        except Exception:
            logging.getLogger(__name__).exception("Sortie fuel use failed")
            fuel_log = []
        self.add_debrief_log(fuel_log)
        log.extend(fuel_log)
        report.add("fuel", fuel_log)
        try:
            from game.logistics.weapon_use import charge_weapon_use

            weapon_log = stats.measure(
                "weapons", lambda: charge_weapon_use(game, debriefing)
            )
            self.add_debrief_log(weapon_log)
            log.extend(weapon_log)
            report.add("weapons", weapon_log)
        except Exception:
            logging.getLogger(__name__).exception("Weapon use failed")
        try:
            from game.logistics.redfor import use_red_sortie_stock

            use_red_sortie_stock(game)
        except Exception:
            logging.getLogger(__name__).exception("REDFOR sortie stock use failed")
        try:
            from game.logistics.intel import record_recon

            recon_log = record_recon(game, debriefing)
            self.add_debrief_log(recon_log)
            log.extend(recon_log)
            report.add("recon", recon_log)
        except Exception:
            logging.getLogger(__name__).exception("Recon intel failed")
        flights_from = len(log)
        stats.start("transfers")
        for t in self._transfers.values():
            if t.status is not TransferStatus.IN_FLIGHT:
                continue
            label = t.cargo_label
            flight = flight_for_transfer(game, t.transfer_id)
            if flight is None:
                t.status = TransferStatus.PLANNED
                continue

            flight_lost = debriefing.air_losses.surviving_flight_members(flight) <= 0

            # Weapon transfers: settled from where the crates ended up, when the
            # mission script reported them (see crate_delivery).
            if t.cargo is not None:
                from game.logistics.crate_delivery import reports_for, settle_transfer

                state = getattr(debriefing, "state_data", None)
                reports = reports_for(
                    list(getattr(state, "cargo_crates", None) or []), t.transfer_id
                )
                if reports:
                    log.extend(settle_transfer(game, self, t, reports, flight_lost))
                    continue

            if flight_lost:
                t.mark_failed()
                log.append(f"Transfer {t.transfer_id[:8]}: flight lost, {label} lost")
                continue

            source = control_point(game, t.source_cp_id)
            destination = control_point(game, t.dest_cp_id)
            dest_wh = self._warehouses.get(t.dest_cp_id)
            if (
                destination is None
                or destination.captured is not Player.BLUE
                or source is None
                or source.captured is not Player.BLUE
                or (dest_wh is None and t.cargo is None)
            ):
                t.mark_failed()
                log.append(
                    f"Transfer {t.transfer_id[:8]}: base changed hands, {label} lost"
                )
                continue

            if t.cargo is not None:
                from game.logistics.cargo import manifest_summary

                delivered_items, overflow_items = self._deliver_weapons(
                    t, t.source_cp_id, t.dest_cp_id, destination.name
                )
                t.mark_delivered(float(sum(delivered_items.values())))
                line = (
                    f"Transfer {t.transfer_id[:8]}: "
                    f"{manifest_summary(delivered_items) or 'nothing'} "
                    f"delivered to {destination.name}"
                )
                if overflow_items:
                    line += (
                        f", {manifest_summary(overflow_items)} returned to "
                        f"{source.name} (no room)"
                    )
                log.append(line)
                continue

            if dest_wh is None:  # checked above for category transfers
                continue
            item = dest_wh.stock[t.category]
            delivered = min(t.quantity, max(0.0, item.capacity - item.quantity))
            item.apply_delivery(delivered)
            t.mark_delivered(delivered)
            line = (
                f"Transfer {t.transfer_id[:8]}: {delivered:.0f} {t.category.value} "
                f"delivered to {destination.name}"
            )
            overflow = t.quantity - delivered
            if overflow > 0:
                src_wh = self._warehouses.get(t.source_cp_id)
                if src_wh is not None:
                    src_wh.stock[t.category].apply_delivery(overflow)
                    line += f", {overflow:.0f} returned to {source.name} (no room)"
                else:
                    line += f", {overflow:.0f} lost (no room)"
            log.append(line)

        stats.stop("transfers")
        stats.save()

        # Naval munitions crates flown to ships (ship_weapons plugin).
        from game.logistics.naval_munitions import settle as settle_naval

        state = getattr(debriefing, "state_data", None)
        log.extend(
            settle_naval(game, list(getattr(state, "naval_munitions", None) or []))
        )
        report.add("flights", log[flights_from:])
        try:
            report.add("supply", turn_report.supply_warnings(game))
        except Exception:
            logging.getLogger(__name__).exception("Turn report supply warnings failed")
        return log

    # ── Base captures and the debrief log ─────────────────────────────

    def on_base_captured(self, cp: Any, new_owner: Any) -> List[str]:
        """A base changed hands: weapons to 0, fuel kept (see logistics/capture.py)."""
        from game.logistics.capture import on_base_captured
        from game.logistics.intel import forget

        forget(self, cp.id)

        log = on_base_captured(self, cp, new_owner)
        self.add_debrief_log(log)
        return log

    def add_debrief_log(self, lines: List[str]) -> None:
        """Lines for the debrief window's "Logistics & Warehouse changes"."""
        self._debrief_log.extend(lines)

    def pop_debrief_log(self) -> List[str]:
        lines = list(self._debrief_log)
        self._debrief_log = []
        return lines

    def cancel_transfer(self, transfer_id: str) -> bool:
        t = self._transfers.get(transfer_id)
        if t is None or t.status != TransferStatus.PLANNED:
            return False
        if t.cargo is not None:
            self._return_weapons(t.source_cp_id, t.cargo)
        else:
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
