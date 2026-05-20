"""
game/logistics/debrief_hook.py

Processes a completed mission debriefing and updates the logistics warehouse
stock based on what happened in the mission:

- Destroyed fuel depots  → reduce fuel stock at that base
- Destroyed ammo depots  → reduce ammunition stock at that base
- Base captures by RED   → zero all stock except fuel
- Base captures by BLUE  → add base to warehouse network with salvage stock
- Completed LOGISTIC flights → credit fuel/ammo delivered to destination base

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
FUEL_LOSS_PER_DEPOT_UNIT   = 150.0
AMMO_LOSS_PER_DEPOT_UNIT   = 100.0
SUPPLY_LOSS_PER_DEPOT_UNIT = 50.0

# Salvage stock added when blue captures a red base
CAPTURE_SALVAGE_STOCK = 200.0

# ── Logistic flight delivery amounts ──────────────────────────────────────────
# How much fuel (in StockItem units) one successful logistic flight delivers.
# These map to WarehouseCategory.FUEL and .AMMUNITION in __init__.py.
# Tune alongside FUEL_DELIVERY_PCT / AMMO_DELIVERY_PCT in logistic_planner.py.
LOGISTIC_FUEL_DELIVERY   = 200.0   # units of fuel per completed flight
LOGISTIC_AMMO_DELIVERY   = 150.0   # units of ammo per completed flight
# ─────────────────────────────────────────────────────────────────────────────


def update_logistics_from_debriefing(debriefing: "Debriefing") -> List[str]:
    """
    Main entry point. Call from QDebriefingWindow.closeEvent.

    Returns a list of human-readable log lines describing what changed.

    CONCEPT — why this function exists:
        DCS runs the actual mission. When it ends, Retribution reads back
        what happened (the Debriefing object). This function translates those
        events into changes to the Python logistics model so the next turn
        reflects what actually occurred in-game.

        For logistic flights specifically: the Lua script (logistic_supply.lua)
        already moved fuel in the DCS warehouse during the mission. Here we
        mirror that change back into the Python StockItem quantities so the
        campaign's supply model stays in sync with DCS.
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
            wh  = logistics.get_warehouse(cp.id)

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
    # 2. Completed LOGISTIC flights → credit deliveries
    #
    # CONCEPT — how we know a logistic flight succeeded:
    #   debriefing.state.flight_states maps each Flight object to its
    #   MissionResult. We filter for LOGISTIC flights and check if the
    #   aircraft survived (returned home). If it did, the Lua plugin
    #   already transferred the DCS warehouse quantities, so we mirror
    #   the same amounts into our Python StockItem model here.
    #
    #   If the aircraft was shot down, the delivery never happened —
    #   we don't credit anything, which naturally penalises failed runs.
    # ------------------------------------------------------------------
    try:
        from game.ato.flighttype import FlightType

        for flight, state in debriefing.state.flight_states.items():
            if flight.flight_type is not FlightType.LOGISTIC:
                continue

            # MissionResult has a succeeded or returned_to_base attribute;
            # check whichever your Retribution version uses.
            # Common patterns: state.returned_to_base, state.success,
            # or state == MissionResult.SUCCESS.
            # We try both gracefully.
            completed = (
                getattr(state, "returned_to_base", False)
                or getattr(state, "success", False)
                or str(state).lower() in ("success", "returned")
            )

            if not completed:
                logger.debug(
                    f"Logistic flight {flight.group_name} did not complete — "
                    f"no supply credit applied."
                )
                continue

            # The destination is the package target CP
            dest_cp = getattr(flight.package, "target", None)
            if dest_cp is None:
                continue

            dest_wh = logistics.get_warehouse(dest_cp.id)
            if dest_wh is None:
                # Base has no warehouse yet — create one with zero stock
                from game.logistics import Warehouse
                dest_wh = Warehouse(cp_id=dest_cp.id, cp_name=dest_cp.name)
                logistics._warehouses[dest_cp.id] = dest_wh
                logger.debug(
                    f"Logistic debrief: created new warehouse for {dest_cp.name}"
                )

            # Credit fuel
            _add(
                dest_wh,
                WarehouseCategory.FUEL,
                LOGISTIC_FUEL_DELIVERY,
                log,
                f"{dest_cp.name}: +{LOGISTIC_FUEL_DELIVERY:.0f} fuel "
                f"(logistic flight {flight.group_name})",
            )

            # Credit ammo
            _add(
                dest_wh,
                WarehouseCategory.AMMUNITION,
                LOGISTIC_AMMO_DELIVERY,
                log,
                f"{dest_cp.name}: +{LOGISTIC_AMMO_DELIVERY:.0f} ammo "
                f"(logistic flight {flight.group_name})",
            )

            # Also reduce origin stock (supplies were loaded from there)
            origin_cp = getattr(flight, "from_cp", None)
            if origin_cp is not None:
                origin_wh = logistics.get_warehouse(origin_cp.id)
                if origin_wh is not None:
                    _reduce(
                        origin_wh,
                        WarehouseCategory.FUEL,
                        LOGISTIC_FUEL_DELIVERY,
                        log,
                        f"{origin_cp.name}: -{LOGISTIC_FUEL_DELIVERY:.0f} fuel "
                        f"(loaded onto logistic flight {flight.group_name})",
                    )

    except Exception as e:
        logger.debug(f"Logistics debrief: error processing logistic flights: {e}")

    # ------------------------------------------------------------------
    # 3. Base captures
    # ------------------------------------------------------------------
    for capture in debriefing.base_captures:
        cp               = capture.control_point
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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _reduce(
    wh: "Warehouse",
    category: "WarehouseCategory",
    amount: float,
    log: List[str],
    description: str,
) -> None:
    """Subtract amount from a warehouse category, clamped to zero."""
    before = wh.stock[category].quantity
    wh.stock[category].quantity = max(0.0, before - amount)
    lost = before - wh.stock[category].quantity
    if lost > 0:
        log.append(f"{description} (-{lost:.0f} {category.value})")


def _add(
    wh: "Warehouse",
    category: "WarehouseCategory",
    amount: float,
    log: List[str],
    description: str,
) -> None:
    """
    Add amount to a warehouse category, clamped to capacity.

    CONCEPT — why clamp to capacity:
        StockItem has both quantity and capacity fields. We never want
        to credit more than the base can physically store — that would
        make the supply model lie about what's available.
    """
    before   = wh.stock[category].quantity
    capacity = wh.stock[category].capacity
    wh.stock[category].quantity = min(capacity, before + amount)
    gained   = wh.stock[category].quantity - before
    if gained > 0:
        log.append(f"{description} (+{gained:.0f} {category.value})")


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
