"""Naval munitions crates: how ships are rearmed at sea.

A helicopter loads a naval munitions crate at a friendly base (F10 menu, see
resources/plugins/ship_weapons/ship_weapons.lua), flies it to a friendly ship,
lands on the deck and stays 15 minutes: that is one 20% rearm load.

Each crate is taken from the base's Ammunition warehouse stock. This module
writes how many crates each base can hand out into the mission, and charges
the stock for the crates that were loaded (net of crates brought back).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Mapping
from uuid import UUID

from game.logistics.crate_delivery import base_radius_m, friendly_bases

if TYPE_CHECKING:
    from game import Game
    from game.logistics import LogisticsManager

logger = logging.getLogger(__name__)

#: Weight of one crate in the helicopter (kg). Light enough for a UH-1H at
#: full fuel (about 800 kg of payload).
CRATE_KG = 500.0
#: Ammunition warehouse stock one crate uses.
AMMO_PER_CRATE = 50.0


def script_data(game: Game) -> Dict[str, Any]:
    """The table the mission script reads: bases and crates available."""
    from game.logistics import Warehouse, WarehouseCategory

    logistics: LogisticsManager = game.logistics
    bases: List[Dict[str, Any]] = []
    for cp in friendly_bases(game):
        wh = logistics.get_warehouse(cp.id)
        if wh is None:
            # Same default warehouse the Logistics window creates for a base.
            wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
            logistics.add_warehouse(wh)
        ammo = wh.stock[WarehouseCategory.AMMUNITION].quantity
        bases.append(
            {
                "id": str(cp.id),
                "name": cp.name,
                "x": cp.position.x,
                "z": cp.position.y,
                "radius": base_radius_m(cp),
                "crates": int(ammo // AMMO_PER_CRATE),
            }
        )
    return {"crateKg": CRATE_KG, "bases": bases}


def settle(game: Game, reports: List[Mapping[str, Any]]) -> List[str]:
    """Charge each base's ammunition stock for the crates it handed out.

    A report is {"base": id, "name": name, "loaded": n, "delivered": m}:
    loaded counts crates taken and not brought back.
    """
    from game.logistics import WarehouseCategory

    logistics: LogisticsManager = game.logistics
    log: List[str] = []
    for report in reports:
        try:
            loaded = int(report.get("loaded") or 0)
            delivered = int(report.get("delivered") or 0)
            base_id = UUID(str(report.get("base")))
        except (TypeError, ValueError):
            logger.warning("Unreadable naval munitions report: %r", report)
            continue
        name = str(report.get("name") or base_id)
        if loaded <= 0:
            continue
        wh = logistics.get_warehouse(base_id)
        if wh is None:
            log.append(
                f"Naval munitions: {loaded} crate(s) from {name}, base no longer ours"
            )
            continue
        item = wh.stock[WarehouseCategory.AMMUNITION]
        before = item.quantity
        item.apply_consumption(loaded * AMMO_PER_CRATE)
        line = (
            f"Naval munitions: {loaded} crate(s) taken from {name} "
            f"(-{before - item.quantity:.0f} ammunition)"
        )
        if delivered:
            line += f", {delivered} delivered to ships"
        lost = loaded - delivered
        if lost > 0:
            line += f", {lost} not delivered (lost or still aboard)"
        log.append(line)
    return log
