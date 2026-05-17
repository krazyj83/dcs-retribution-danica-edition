"""
game/logistics/debrief_hook.py

Processes a completed mission debriefing and updates the logistics warehouse
stock based on what happened in the mission:

  - Destroyed fuel depots  → reduce fuel stock at that base
  - Destroyed ammo depots  → reduce ammunition stock at that base
  - Base captures by RED   → zero all stock except fuel
  - Base captures by BLUE  → add base to warehouse network with salvage stock

Called from QDebriefingWindow.closeEvent after the mission ends.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from game.debriefing import Debriefing
    from game.logistics import LogisticsManager, Warehouse, WarehouseCategory

logger = logging.getLogger(__name__)

# Stock lost per destroyed depot unit — tune to taste
FUEL_LOSS_PER_DEPOT_UNIT    = 150.0
AMMO_LOSS_PER_DEPOT_UNIT    = 100.0
SUPPLY_LOSS_PER_DEPOT_UNIT  =  50.0

# Salvage stock added when blue captures a red base
CAPTURE_SALVAGE_STOCK = 200.0


def update_logistics_from_debriefing(debriefing: "Debriefing") -> List[str]:
    """
    Main entry point. Call from QDebriefingWindow.closeEvent.
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
                        f"{cp.name}: supplies lost from fuel depot destruction")

            elif cat == "aa" or _is_ammo_depot(tgo):
                _reduce(wh, WarehouseCategory.AMMUNITION, AMMO_LOSS_PER_DEPOT_UNIT, log,
                        f"{cp.name}: ammo depot destroyed")

        except Exception as e:
            logger.debug(f"Logistics debrief: error processing ground object loss: {e}")

    # ------------------------------------------------------------------
    # 2. Base captures
    # ------------------------------------------------------------------
    for capture in debriefing.base_captures:
        cp = capture.control_point
        captured_by_player = capture.captured_by_player

        try:
            if captured_by_player.is_blue:
                # Blue captured a red base — add to warehouse network with salvage
                from game.logistics import Warehouse
                new_wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
                for cat in WarehouseCategory:
                    new_wh.stock[cat].quantity = CAPTURE_SALVAGE_STOCK
                logistics._warehouses[cp.id] = new_wh
                log.append(
                    f"{cp.name} captured by blue — added to warehouse network "
                    f"with {CAPTURE_SALVAGE_STOCK:.0f} salvage stock per category"
                )

            else:
                # Red captured a blue base — zero everything EXCEPT fuel
                wh = logistics.get_warehouse(cp.id)
                if wh is not None:
                    for cat in WarehouseCategory:
                        if cat == WarehouseCategory.FUEL:
                            # Fuel infrastructure stays — tanks don't move
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
    before = wh.stock[category].quantity
    wh.stock[category].quantity = max(0.0, before - amount)
    lost = before - wh.stock[category].quantity
    if lost > 0:
        log.append(f"{description} (-{lost:.0f} {category.value})")


def _is_ammo_depot(tgo) -> bool:
    try:
        return tgo.is_ammo_depot
    except AttributeError:
        pass
    try:
        name = tgo.name.lower()
        return "ammo" in name or "ammunition" in name or "depot" in name
    except Exception:
        return False
