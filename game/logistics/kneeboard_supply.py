"""What a player flight's bases hold, for the "Base Supply" kneeboard page.

    DEPARTURE  Kutaisi                     ARRIVAL  Senaki
    Fuel         1,520 / 2,000  76%  OK    ...
    Ammunition     300 / 1,000  30%  LOW
    Supplies       ...
    ! ammunition 30%

    Weapons for the F/A-18C          (departure base: a table)
    AGM-88C                    0  EMPTY
    GBU-12                     6  LOW
    AIM-120C                  34

    Empty: AGM-88C. Low: GBU-12 (6)  (arrival / divert: one summary line)

Only BLUEFOR bases with a warehouse are shown (ships and off-map spawns are
supplied differently). The numbers are the same ones the Base Inventory tab,
the Logistics window and the map rings use (levels.py, supply_status.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

#: Weapon rows in the departure base's table before "+N more", so three bases
#: still fit on one page. Arrival and divert get a one-line summary of their
#: empty and low weapons instead (what matters when rearming there).
MAX_WEAPON_ROWS = 12
#: Weapons named in an arrival/divert summary before "+N more".
MAX_SUMMARY_NAMES = 6


@dataclass
class StockLine:
    label: str
    quantity: float
    capacity: float
    status: str  # "ok", "low", "critical", "empty" or "unlimited"

    @property
    def percent(self) -> str:
        from game.logistics.levels import level

        return f"{level(self.quantity, self.capacity):.0%}"


@dataclass
class WeaponLine:
    name: str
    quantity: int
    flag: str  # "", "LOW" or "EMPTY"


@dataclass
class BaseSupplyInfo:
    role: str  # "Departure", "Arrival" or "Divert"
    name: str
    #: False for ships and off-map spawns: nothing else is filled in.
    has_warehouse: bool = True
    stock: List[StockLine] = field(default_factory=list)
    fuel_turns_left: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    #: None when the base's weapon stores were never synced. Departure: the
    #: table's rows; arrival/divert: only the empty and low weapons.
    weapons: Optional[List[WeaponLine]] = None
    hidden_weapons: int = 0

    @property
    def summary(self) -> str:
        """Arrival/divert: "Empty: A, B. Low: C (6)." in one line."""
        if not self.weapons:
            return "No empty or low weapons."
        shown = self.weapons[:MAX_SUMMARY_NAMES]
        empty = [short_name(w.name, 28) for w in shown if w.flag == "EMPTY"]
        low = [
            f"{short_name(w.name, 28)} ({w.quantity})" for w in shown if w.flag == "LOW"
        ]
        parts = []
        if empty:
            parts.append("Empty: " + ", ".join(empty) + ".")
        if low:
            parts.append("Low: " + ", ".join(low) + ".")
        more = len(self.weapons) - len(shown)
        if more:
            parts.append(f"+{more} more.")
        return " ".join(parts)


def control_point_named(game: Any, name: str) -> Any:
    for cp in game.theater.controlpoints:
        if cp.name == name:
            return cp
    return None


def aircraft_weapon_ids(aircraft_type: Any) -> Set[str]:
    """DCS ids of everything the aircraft can carry."""
    from game.data.weapons import Pylon

    ids: Set[str] = set()
    try:
        for pylon in Pylon.iter_pylons(aircraft_type):
            ids.update(weapon.clsid for weapon in pylon.allowed)
    except Exception:
        pass
    return ids


def _weapon_lines(inventory: Any, allowed: Set[str]) -> List[WeaponLine]:
    """This aircraft's weapons in store, one line per weapon name; empty and
    low ones first (what the player most needs to know), then by name."""
    from game.logistics.base_inventory import GROUND_UNIT_CATEGORIES
    from game.logistics.base_inventory import LOW_WEAPON_QUANTITY

    merged: Dict[str, int] = {}
    for item in inventory.items.values():
        if item.clsid not in allowed or item.category in GROUND_UNIT_CATEGORIES:
            continue
        merged[item.name] = merged.get(item.name, 0) + int(item.quantity)
    lines = []
    for name, quantity in merged.items():
        if quantity <= 0:
            flag = "EMPTY"
        elif quantity < LOW_WEAPON_QUANTITY:
            flag = "LOW"
        else:
            flag = ""
        lines.append(WeaponLine(name, quantity, flag))
    order = {"EMPTY": 0, "LOW": 1, "": 2}
    return sorted(lines, key=lambda w: (order[w.flag], w.name.lower()))


def base_supply_info(
    game: Any, cp: Any, role: str, aircraft_type: Any
) -> Optional[BaseSupplyInfo]:
    """The page's numbers for one base, or None if it isn't a BLUEFOR base."""
    from game.logistics import WarehouseCategory, keeps_warehouse
    from game.logistics.levels import level, level_status
    from game.logistics.supply_status import supply_status

    if cp is None or not cp.captured.is_blue:
        return None
    if not keeps_warehouse(cp):
        return BaseSupplyInfo(role=role, name=cp.name, has_warehouse=False)
    status = next((s for s in supply_status(game) if s.cp is cp), None)
    if status is None:
        return None

    info = BaseSupplyInfo(role=role, name=cp.name)
    for label, quantity, capacity in (
        (WarehouseCategory.FUEL, status.fuel, status.fuel_capacity),
        (WarehouseCategory.AMMUNITION, status.ammunition, status.ammunition_capacity),
        (WarehouseCategory.SUPPLIES, status.supplies, status.supplies_capacity),
    ):
        state = level_status(level(quantity, capacity))
        if label is WarehouseCategory.FUEL and status.unlimited_fuel:
            state = "unlimited"
        info.stock.append(
            StockLine(label.value.capitalize(), quantity, capacity, state)
        )
    info.fuel_turns_left = status.fuel_turns_left
    info.warnings = list(status.reasons)

    inventory = game.logistics.get_weapon_inventory(cp.id)
    if inventory is not None:
        lines = _weapon_lines(inventory, aircraft_weapon_ids(aircraft_type))
        if role == "Departure":
            info.weapons = lines[:MAX_WEAPON_ROWS]
            info.hidden_weapons = max(0, len(lines) - MAX_WEAPON_ROWS)
        else:
            info.weapons = [w for w in lines if w.flag]
    return info


def flight_bases(game: Any, flight: Any) -> List[BaseSupplyInfo]:
    """Departure, then arrival and divert when they are other bases."""
    result: List[BaseSupplyInfo] = []
    seen: Set[str] = set()
    for role, runway in (
        ("Departure", flight.departure),
        ("Arrival", flight.arrival),
        ("Divert", flight.divert),
    ):
        if runway is None or runway.airfield_name in seen:
            continue
        seen.add(runway.airfield_name)
        cp = control_point_named(game, runway.airfield_name)
        if cp is None and role == "Departure":
            cp = getattr(flight.squadron, "location", None)
        info = base_supply_info(game, cp, role, flight.aircraft_type)
        if info is not None:
            result.append(info)
    return result


def short_name(name: str, length: int) -> str:
    """One kneeboard line: long DCS weapon names are cut with "..."."""
    return name if len(name) <= length else name[: length - 3].rstrip() + "..."
