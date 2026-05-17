"""
game/logistics/debrief_hook.py

Processes a completed mission debriefing and updates the logistics warehouse
stock based on what happened in the mission:

  - Destroyed fuel depots  → reduce fuel stock at that base
  - Destroyed ammo depots  → reduce ammunition stock at that base
  - Base captures          → transfer warehouse to new owner (or clear it)

Called from QDebriefingWindow.closeEvent after the mission ends.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from game.debriefing import Debriefing
    from game.logistics import LogisticsManager, Warehouse
    from game.logistics import WarehouseCategory

logger = logging.getLogger(__name__)

# How much stock is lost per destroyed depot unit.
# These are tunable — adjust to taste.
FUEL_LOSS_PER_DEPOT_UNIT   = 150.0   # litres / tons
AMMO_LOSS_PER_DEPOT_UNIT   = 100.0   # rounds / crates
SUPPLY_LOSS_PER_DEPOT_UNIT =  50.0   # crates

# Fraction of warehouse stock transferred when a base is captured by the enemy.
# 0.0 = all stock lost, 1.0 = all stock transferred to new owner.
CAPTURE_STOCK_RETENTION = 0.3


def update_logistics_from_debriefing(debriefing: Debriefing) -> List[str]:
    """
    Main entry point. Call this from QDebriefingWindow.closeEvent.

    Returns a list of human-readable log lines describing what changed,
    suitable for display in the UI or logging.
    """
    game = debriefing.game

    if not hasattr(game, "logistics") or game.logistics is None:
        return []

    from game.logistics import LogisticsManager, WarehouseCategory
    logistics: LogisticsManager = game.logistics

    log: List[str] = []

    # ------------------------------------------------------------------
    # 1. Destroyed ground objects — check for fuel / ammo depots
    # ------------------------------------------------------------------
    for mapping in debriefing.ground_object_losses:
        try:
            tgo = mapping.theater_unit.ground_object
            cp  = tgo.control_point
            cat = getattr(tgo, "category", None)

            wh = logistics.get_warehouse(cp.id)
            if wh is None:
                continue

            if cat == "fuel":
                _reduce(wh, WarehouseCategory.FUEL, FUEL_LOSS_PER_DEPOT_UNIT, log,
                        f"{cp.name}: fuel depot destroyed")
                _reduce(wh, WarehouseCategory.SUPPLIES, SUPPLY_LOSS_PER_DEPOT_UNIT, log,
                        f"{cp.name}: supply loss from fuel depot")

            elif cat == "aa" or _is_ammo_depot(tgo):
                _reduce(wh, WarehouseCategory.AMMUNITION, AMMO_LOSS_PER_DEPOT_UNIT, log,
                        f"{cp.name}: ammo depot destroyed")

        except Exception as e:
            logger.debug(f"Logistics debrief: error processing ground object loss: {e}")

    # ------------------------------------------------------------------
    # 2. Base captures — transfer or clear warehouse
    # ------------------------------------------------------------------
    for capture in debriefing.base_captures:
        cp = capture.control_point
        captured_by_player = capture.captured_by_player

        wh = logistics.get_warehouse(cp.id)
        if wh is None:
            continue

        try:
            if captured_by_player.is_blue:
                # Blue captured a red base — no warehouse to transfer (red bases
                # aren't tracked), but add the base to blue warehouses with
                # partial stock representing salvage.
                from game.logistics import Warehouse, StockItem
                new_wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
                for cat in WarehouseCategory:
                    # Start with a small salvage amount
                    new_wh.stock[cat].quantity = 200.0
                logistics._warehouses[cp.id] = new_wh
                log.append(f"{cp.name} captured by blue — added to warehouse network")

            else:
                # Red captured a blue base — lose most of the stock
                for cat in WarehouseCategory:
                    original = wh.stock[cat].quantity
                    wh.stock[cat].quantity = round(original * CAPTURE_STOCK_RETENTION, 1)
                    lost = original - wh.stock[cat].quantity
                    if lost > 0:
                        log.append(
                            f"{cp.name} captured by red — lost {lost:.0f} {cat.value}"
                        )
                # Remove from blue warehouse network
                logistics._warehouses.pop(cp.id, None)

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
    """Reduce warehouse stock by amount, clamping to zero."""
    from game.logistics import WarehouseCategory
    before = wh.stock[category].quantity
    wh.stock[category].quantity = max(0.0, before - amount)
    lost = before - wh.stock[category].quantity
    if lost > 0:
        log.append(f"{description} (-{lost:.0f} {category.value})")


def _is_ammo_depot(tgo) -> bool:
    """Heuristic check for whether a TGO is an ammo depot."""
    try:
        return tgo.is_ammo_depot
    except AttributeError:
        pass
    try:
        name = tgo.name.lower()
        return "ammo" in name or "ammunition" in name or "depot" in name
    except Exception:
        return False
