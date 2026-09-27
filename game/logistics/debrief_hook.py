"""
game/logistics/debrief_hook.py

Processes a completed mission debriefing and updates the logistics warehouse
stock based on what happened in the mission:

- Destroyed fuel depots  → reduce fuel stock at that base
- Destroyed ammo depots  → reduce ammunition stock at that base
- SAM site knocked out   → reduce ammunition stock at its base, once per site
- Base captures by RED   → zero all stock except fuel
- Base captures by BLUE  → add base to warehouse network with salvage stock

Called when the debrief window opens, after the mission results are processed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from game.debriefing import Debriefing
    from game.logistics import LogisticsManager, Warehouse, WarehouseCategory

logger = logging.getLogger(__name__)

# Stock lost per destroyed depot unit — tune to taste
FUEL_LOSS_PER_DEPOT_UNIT = 150.0
AMMO_LOSS_PER_DEPOT_UNIT = 100.0
SUPPLY_LOSS_PER_DEPOT_UNIT = 50.0

# Ammunition lost when a SAM site is knocked out (no working air defence left),
# charged once per site and scaled by the site's size (all its vehicles,
# launchers, radars and support trucks):
#   SA-13 pair (2) 20 | SA-6 battery (8) 80 | Hawk (12) 120 | Patriot (17) 170
SAM_SITE_AMMO_PER_UNIT = 10.0
SAM_SITE_AMMO_MIN = 20.0
SAM_SITE_AMMO_MAX = 200.0


def sam_site_ammo_loss(unit_count: int) -> float:
    """Ammunition a knocked-out SAM site of this many vehicles costs its base."""
    loss = SAM_SITE_AMMO_PER_UNIT * max(0, unit_count)
    return min(SAM_SITE_AMMO_MAX, max(SAM_SITE_AMMO_MIN, loss))


# Salvage stock added when blue captures a red base
CAPTURE_SALVAGE_STOCK = 200.0


def update_logistics_from_debriefing(debriefing: "Debriefing") -> List[str]:
    """
    Main entry point, called by QDebriefingWindow.
    Returns a list of human-readable log lines describing what changed.
    """
    game = debriefing.game

    if not hasattr(game, "logistics") or game.logistics is None:
        return []

    from game.logistics import LogisticsManager, WarehouseCategory

    logistics: LogisticsManager = game.logistics
    log: List[str] = []

    # ------------------------------------------------------------------
    # 1. Destroyed ground objects — fuel and ammo depots
    # ------------------------------------------------------------------
    # SAM sites that lost units this mission, keyed by object so each site
    # is looked at once however many of its vehicles died.
    sam_sites_hit: Dict[int, Any] = {}

    for mapping in debriefing.ground_object_losses:
        try:
            tgo = mapping.theater_unit.ground_object
            cp = tgo.control_point
            cat = getattr(tgo, "category", None)

            if cat == "aa":
                sam_sites_hit[id(tgo)] = tgo
                continue

            # Base ids are UUIDs, despite the int annotations in LogisticsManager.
            cp_id: Any = cp.id
            wh = logistics.get_warehouse(cp_id)
            if wh is None:
                continue

            if cat == "fuel":
                _reduce(
                    wh,
                    WarehouseCategory.FUEL,
                    FUEL_LOSS_PER_DEPOT_UNIT,
                    log,
                    f"{cp.name}: fuel depot destroyed",
                )
                _reduce(
                    wh,
                    WarehouseCategory.SUPPLIES,
                    SUPPLY_LOSS_PER_DEPOT_UNIT,
                    log,
                    f"{cp.name}: supplies lost from fuel depot destruction",
                )

            elif _is_ammo_depot(tgo):
                _reduce(
                    wh,
                    WarehouseCategory.AMMUNITION,
                    AMMO_LOSS_PER_DEPOT_UNIT,
                    log,
                    f"{cp.name}: ammo depot destroyed",
                )

        except Exception as e:
            logger.debug(f"Logistics debrief: error processing ground object loss: {e}")

    # A SAM site costs its base munitions only when it is knocked out: no
    # working air-defence unit left. Losses are already applied to the units
    # when this runs (the debrief window opens after the results are processed).
    for tgo in sam_sites_hit.values():
        try:
            if tgo.has_aa:
                continue
            cp = tgo.control_point
            sam_cp_id: Any = cp.id
            wh = logistics.get_warehouse(sam_cp_id)
            if wh is None:
                continue
            size = int(getattr(tgo, "unit_count", 0) or 0)
            _reduce(
                wh,
                WarehouseCategory.AMMUNITION,
                sam_site_ammo_loss(size),
                log,
                f"{cp.name}: SAM site {tgo.name} ({size} vehicles) knocked out, "
                "munitions lost",
            )
        except Exception as e:
            logger.debug(f"Logistics debrief: error processing SAM site loss: {e}")

    # ------------------------------------------------------------------
    # 2. Base captures
    # ------------------------------------------------------------------
    for capture in debriefing.base_captures:
        cp = capture.control_point
        captured_by_player = capture.captured_by_player
        capture_cp_id: Any = cp.id
        try:
            if captured_by_player.is_blue:
                # Blue captured a red base — add to warehouse network with salvage
                from game.logistics import Warehouse

                new_wh = Warehouse(cp_id=capture_cp_id, cp_name=cp.name)
                for cat in WarehouseCategory:
                    new_wh.stock[cat].quantity = CAPTURE_SALVAGE_STOCK
                logistics._warehouses[capture_cp_id] = new_wh
                log.append(
                    f"{cp.name} captured by blue — added to warehouse network "
                    f"with {CAPTURE_SALVAGE_STOCK:.0f} salvage stock per category"
                )
            else:
                # Red captured a blue base — zero everything EXCEPT fuel
                wh = logistics.get_warehouse(capture_cp_id)
                if wh is not None:
                    for cat in WarehouseCategory:
                        if cat == WarehouseCategory.FUEL:
                            log.append(
                                f"{cp.name} captured by red — fuel stock retained "
                                f"({wh.stock[cat].quantity:.0f} remaining)"
                            )
                            continue
                        lost = wh.stock[cat].quantity
                        wh.stock[cat].quantity = 0.0
                        if lost > 0:
                            log.append(
                                f"{cp.name} captured by red — "
                                f"{lost:.0f} {cat.value} lost"
                            )
                    logistics._warehouses.pop(capture_cp_id, None)

        except Exception as e:
            logger.debug(f"Logistics debrief: error processing capture event: {e}")

    if log:
        logger.info("Logistics debrief summary:\n" + "\n".join(f"  {l}" for l in log))

    return log


def _reduce(
    wh: "Warehouse",
    category: "WarehouseCategory",
    amount: float,
    log: List[str],
    description: str,
) -> None:
    before = wh.stock[category].quantity
    wh.stock[category].quantity = max(0.0, before - amount)
    lost = before - wh.stock[category].quantity
    if lost > 0:
        log.append(f"{description} (-{lost:.0f} {category.value})")


def _is_ammo_depot(tgo: Any) -> bool:
    try:
        return tgo.is_ammo_depot
    except AttributeError:
        pass
    try:
        name = tgo.name.lower()
        return "ammo" in name or "ammunition" in name or "depot" in name
    except Exception:
        return False
