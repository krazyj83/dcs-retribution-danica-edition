"""BLUEFOR weapons used in a mission come out of their base's weapon stores.

The weapon stores (WeaponInventory) count stores as they hang on a pylon: a
missile, a bomb, or a rack or launcher by its DCS CLSID. After each mission,
for every BLUEFOR aircraft (charged to its departure base):

* shot down: everything on its pylons is lost (missiles, bombs, pods, tanks);
* came back: what it fired is used up. The mission script reports every weapon
  fired (S_EVENT_SHOT, by DCS weapon type), and each shot is matched to a
  store on the aircraft's pylons carrying that weapon. A rack of several (e.g.
  "2 x GBU-12") is used up once all its weapons are fired, so each shot is
  1/N of it, rounded up per store type. Guns, and shots that match no store
  (rockets from a pod: the pod stays), cost nothing.

Player aircraft that loaded on the ground (logistics/ground_loading.py) spawn
empty, so they are charged from what the mission script saw them carry: for
each weapon type, the base's store carrying it (single weapons before racks).

A base out of a weapon only gets a warning line: missions can still be flown
(stores never go below 0). Bases whose weapon stores were never synced are
left alone.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:
    from game import Game

logger = logging.getLogger(__name__)


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


@lru_cache(maxsize=1)
def _pydcs_ids() -> Dict[str, str]:
    """CLSID -> pydcs attribute name (e.g. "AIM_120C", "BRU_33_with_2_x_GBU_12...")."""
    from dcs.weapons_data import Weapons

    ids: Dict[str, str] = {}
    for attr, data in vars(Weapons).items():
        if isinstance(data, dict) and "clsid" in data:
            ids.setdefault(data["clsid"], attr)
    return ids


def store_carries(clsid: str, name: str, weapon_type: str) -> bool:
    """Does this store (a pylon load) carry the fired DCS weapon type?"""
    fired = _norm(weapon_type)
    if len(fired) < 3:
        return False
    return fired in _norm(_pydcs_ids().get(clsid, "")) or fired in _norm(name)


def weapons_per_store(name: str) -> int:
    """How many weapons one store holds: "2 x GBU-12", "GBU-12 * 2" -> 2, else 1."""
    match = re.search(r"(\d+)\s*[xX]\s", name) or re.search(r"\*\s*(\d+)", name)
    return max(1, int(match.group(1))) if match else 1


def _pylon_stores(loadout: Any) -> List[Tuple[str, str]]:
    stores = []
    for weapon in getattr(loadout, "pylons", {}).values():
        if weapon is None or not getattr(weapon, "clsid", None):
            continue
        stores.append((weapon.clsid, str(getattr(weapon, "name", weapon.clsid))))
    return stores


def stores_used(
    loadout: Any, lost: bool, shots: Dict[str, int]
) -> Tuple[Dict[str, float], Dict[str, int]]:
    """(store CLSID -> stores used, unmatched weapon type -> shots)."""
    stores = _pylon_stores(loadout)
    used: Dict[str, float] = defaultdict(float)
    unmatched: Dict[str, int] = {}
    if lost:
        for clsid, _ in stores:
            used[clsid] += 1
        return used, unmatched
    names = dict(stores)
    on_board: Dict[str, int] = defaultdict(int)
    for clsid, _ in stores:
        on_board[clsid] += 1
    for weapon_type, count in shots.items():
        match = next(
            (c for c in on_board if store_carries(c, names[c], weapon_type)), None
        )
        if match is None:
            unmatched[weapon_type] = count
            continue
        fired_stores = count / weapons_per_store(names[match])
        used[match] += min(float(on_board[match]), fired_stores)
    return used, unmatched


def stores_for_ammo(inventory: Any, used: Dict[str, int]) -> Dict[str, float]:
    """Store CLSID -> stores used, for weapons a ground-loaded aircraft used."""
    result: Dict[str, float] = defaultdict(float)
    items = list(getattr(inventory, "items", {}).values())
    for weapon_type, count in used.items():
        matches = [i for i in items if store_carries(i.clsid, i.name, weapon_type)]
        if not matches:
            continue
        # A single weapon first, then the smallest rack.
        best = min(matches, key=lambda i: (weapons_per_store(i.name), i.name))
        result[best.clsid] += count / weapons_per_store(best.name)
    return result


def charge_weapon_use(game: Game, debriefing: Any) -> List[str]:
    """Take the stores BLUEFOR used in the mission from their bases. Log lines."""
    logistics = game.logistics
    unit_map = debriefing.unit_map
    fired = getattr(debriefing.state_data, "weapons_fired", {}) or {}
    ammo_used = getattr(debriefing.state_data, "player_ammo_used", {}) or {}
    from game.logistics.ground_loading import applies_to

    lost_units = {
        (id(unit.flight), id(unit.pilot))
        for unit in getattr(debriefing.air_losses, "player", [])
    }
    member_index: Dict[str, int] = getattr(unit_map, "aircraft_member_index", {})

    used_by_base: Dict[Any, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bases: Dict[Any, Any] = {}
    for unit_name, flying in unit_map.aircraft.items():
        flight = flying.flight
        base = getattr(flight, "departure", None)
        if base is None or not base.captured.is_blue:
            continue
        members = flight.roster.members
        index = member_index.get(unit_name)
        if index is None or index >= len(members):
            continue
        lost = (id(flight), id(flying.pilot)) in lost_units
        bases[base.id] = base
        if applies_to(game, flight, members[index]):
            inventory = logistics.get_weapon_inventory(base.id)
            for clsid, amount in stores_for_ammo(
                inventory, ammo_used.get(unit_name, {})
            ).items():
                used_by_base[base.id][clsid] += amount
            continue
        used, unmatched = stores_used(
            members[index].loadout, lost, fired.get(unit_name, {})
        )
        for weapon_type, count in unmatched.items():
            logger.debug(f"{unit_name}: {count} x {weapon_type} matched no store")
        bases[base.id] = base
        for clsid, amount in used.items():
            used_by_base[base.id][clsid] += amount

    log: List[str] = []
    for base_id, used in used_by_base.items():
        inventory = logistics.get_weapon_inventory(base_id)
        if inventory is None:
            continue
        base = bases[base_id]
        parts: List[str] = []
        empty: List[str] = []
        for clsid, amount in sorted(used.items()):
            item = inventory.items.get(clsid)
            count = math.ceil(amount - 1e-9)
            if item is None or count <= 0:
                continue
            taken = min(item.quantity, count)
            item.quantity -= taken
            parts.append(f"{count} {item.name}")
            if item.quantity <= 0:
                empty.append(item.name)
        if parts:
            log.append(f"{base.name}: used {', '.join(parts)}")
        if empty:
            log.append(f"{base.name}: OUT OF {', '.join(sorted(set(empty)))}")
    for line in log:
        logger.info(f"Weapon use: {line}")
    return log


def weapon_shortages(game: Game, base: Any, loadout: Any, count: int) -> List[str]:
    """Stores of this loadout the base doesn't have enough of for `count` aircraft."""
    inventory = game.logistics.get_weapon_inventory(base.id)
    if inventory is None:
        return []
    need: Dict[str, int] = defaultdict(int)
    names: Dict[str, str] = {}
    for clsid, name in _pylon_stores(loadout):
        need[clsid] += count
        names[clsid] = name
    short = []
    for clsid, amount in need.items():
        item = inventory.items.get(clsid)
        if item is not None and item.quantity < amount:
            short.append(f"{names[clsid]} ({item.quantity} of {amount})")
    return short
