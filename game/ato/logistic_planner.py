"""
game/ato/logistic_planner.py  — NEW FILE

Auto-plans warehouse resupply flights for one coalition each turn.
Works identically for BLUEFOR and REDFOR — pass the correct coalition
and it handles the right side automatically.

Wire it into the AI planner by adding to ai_flight_planner.py:

    from game.ato.logistic_planner import LogisticPlanner

    logistic_planner = LogisticPlanner(game=self.game, coalition=self)
    for pkg in logistic_planner.plan():
        self.ato.add_package(pkg)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from game.ato.flighttype import FlightType
from game.logistics import WarehouseCategory

if TYPE_CHECKING:
    from game.coalition import Coalition
    from game.game import Game
    from game.logistics import LogisticsManager, Warehouse
    from game.ato.package import Package

logger = logging.getLogger(__name__)

# How much stock one logistic flight delivers (in StockItem units).
# These feed into StockItem.apply_delivery() via debrief_hook.py.
FUEL_DELIVERY_UNITS  = 200.0
AMMO_DELIVERY_UNITS  = 150.0

# Maximum logistic flights auto-planned per coalition per turn.
# Prevents the AI flooding the ATO with transport missions.
MAX_LOGISTIC_FLIGHTS = 3

# Per-turn consumption as a fraction of each StockItem's capacity.
# Simulates fuel and ammo usage by stationed units each turn.
FUEL_CONSUMPTION_RATE = 0.05   # 5% of capacity per turn
AMMO_CONSUMPTION_RATE = 0.08   # 8% of capacity per turn


class LogisticPlanner:
    """
    Auto-plans warehouse resupply flights for one coalition each turn.

    Reads supply levels from the LogisticsManager's Warehouse objects
    (game.logistics.__init__) and creates Package + Flight objects for
    the ATO when bases drop below the 40% threshold defined in
    StockItem.needs_resupply.
    """

    def __init__(self, game: Game, coalition: Coalition) -> None:
        self.game      = game
        self.coalition = coalition
        # Use the existing LogisticsManager attached to the game object
        self.logistics: Optional[LogisticsManager] = getattr(game, "logistics", None)

    def plan(self) -> list[Package]:
        """
        Returns a list of new logistic Packages to add to the ATO.

        Steps:
          1. Apply per-turn consumption to all warehouses this coalition owns
          2. Find warehouses below resupply threshold, most urgent first
          3. For each needy base, find a transport-capable squadron and
             create a Package with a LOGISTIC Flight
        """
        if self.logistics is None:
            logger.debug("LogisticPlanner: no LogisticsManager on game, skipping.")
            return []

        self._apply_turn_consumption()

        needy = self._warehouses_needing_resupply()
        if not needy:
            return []

        packages: list[Package] = []
        for cp_id, wh in needy:
            if len(packages) >= MAX_LOGISTIC_FLIGHTS:
                break
            pkg = self._plan_resupply(cp_id, wh)
            if pkg is not None:
                packages.append(pkg)

        if packages:
            side = "blue" if self.coalition.player else "red"
            logger.info(
                "LogisticPlanner [%s]: planned %d logistic flight(s) this turn.",
                side, len(packages),
            )
        return packages

    # ── Private helpers ───────────────────────────────────────────────────────

    def _apply_turn_consumption(self) -> None:
        """
        Reduce stock at all friendly warehouses by the per-turn consumption rate.

        Without consumption the planner would never trigger because warehouses
        would stay at their starting value. Tune FUEL_CONSUMPTION_RATE and
        AMMO_CONSUMPTION_RATE at the top of this file to adjust frequency.
        """
        for cp in self._friendly_cps():
            wh = self.logistics.get_warehouse(cp.id)
            if wh is None:
                continue
            fuel_item = wh.stock.get(WarehouseCategory.FUEL)
            ammo_item = wh.stock.get(WarehouseCategory.AMMUNITION)
            if fuel_item:
                # apply_consumption() is the new method we added to StockItem
                fuel_item.apply_consumption(fuel_item.capacity * FUEL_CONSUMPTION_RATE)
            if ammo_item:
                ammo_item.apply_consumption(ammo_item.capacity * AMMO_CONSUMPTION_RATE)

    def _warehouses_needing_resupply(self) -> list[tuple[int, Warehouse]]:
        """
        Returns (cp_id, Warehouse) pairs for all friendly bases below threshold,
        sorted so the most depleted base (lowest combined stock level) is first.

        StockItem.needs_resupply uses StockItem.level which we added to __init__.py.
        """
        needy = []
        for cp in self._friendly_cps():
            wh = self.logistics.get_warehouse(cp.id)
            if wh is None:
                continue
            fuel_item = wh.stock.get(WarehouseCategory.FUEL)
            ammo_item = wh.stock.get(WarehouseCategory.AMMUNITION)
            fuel_low  = fuel_item is not None and fuel_item.needs_resupply
            ammo_low  = ammo_item is not None and ammo_item.needs_resupply
            if fuel_low or ammo_low:
                combined = (
                    (fuel_item.level if fuel_item else 1.0) +
                    (ammo_item.level if ammo_item else 1.0)
                )
                needy.append((cp.id, wh, combined))

        # Sort: lowest combined level = most urgent = first
        needy.sort(key=lambda t: t[2])
        return [(cp_id, wh) for cp_id, wh, _ in needy]

    def _plan_resupply(self, dest_cp_id: int, dest_wh: Warehouse) -> Optional[Package]:
        """
        Creates a Package containing one LOGISTIC Flight targeting dest_cp_id.
        Returns None if no transport-capable squadron is available.
        """
        # Lazy imports avoid circular import errors — standard pattern here
        from game.ato.package import Package
        from game.ato.flight import Flight

        dest_cp = self._find_cp_by_id(dest_cp_id)
        if dest_cp is None:
            return None

        origin_cp, squadron = self._find_transport_squadron(exclude_cp=dest_cp)
        if origin_cp is None or squadron is None:
            logger.debug(
                "LogisticPlanner: no transport squadron found for %s",
                getattr(dest_cp, "name", dest_cp_id),
            )
            return None

        dest_fuel = dest_wh.stock.get(WarehouseCategory.FUEL)
        dest_ammo = dest_wh.stock.get(WarehouseCategory.AMMUNITION)

        fuel_to_deliver = FUEL_DELIVERY_UNITS if (dest_fuel and dest_fuel.needs_resupply) else 0.0
        ammo_to_deliver = AMMO_DELIVERY_UNITS if (dest_ammo and dest_ammo.needs_resupply) else 0.0

        package = Package(target=dest_cp, auto_asap=True)

        flight = Flight(
            package    = package,
            country    = self.coalition.country,
            squadron   = squadron,
            count      = 1,
            flight_type = FlightType.LOGISTIC,
            start_type = "Warm",
        )

        # logistic_payload is read by:
        #   - logistic_plugin_injector.py  → builds the Lua data table for in-mission
        #   - debrief_hook.py              → records delivery after mission ends
        flight.logistic_payload = {
            # For the Lua plugin (converts stock units → kg for DCS warehouse API)
            "fuel_kg":          fuel_to_deliver * 250.0,
            "ammo_items":       self._build_ammo_items(dest_ammo),
            "origin_base_name": getattr(origin_cp, "dcs_identifier", origin_cp.name),
            "dest_base_name":   getattr(dest_cp,   "dcs_identifier", dest_cp.name),
            # For debrief_hook.py (Python stock units)
            "dest_cp_id":       dest_cp_id,
            "dest_cp_name":     getattr(dest_cp, "name", str(dest_cp_id)),
            "fuel_delivered":   fuel_to_deliver,
            "ammo_delivered":   ammo_to_deliver,
        }

        package.add_flight(flight)
        return package

    def _build_ammo_items(self, ammo_item) -> list[dict]:
        """
        Returns the ammo_items list for the Lua plugin when ammo is low.
        Each entry is {"item": DCS_clsid_string, "count": int}.
        Returns an empty list when ammo does not need resupply.
        """
        if ammo_item is None or not ammo_item.needs_resupply:
            return []
        # Generic mixed load — adapt per faction later if needed
        return [
            {"item": "weapons.missiles.AIM_120C", "count": 8},
            {"item": "weapons.missiles.AIM_9X",   "count": 8},
            {"item": "weapons.bombs.Mk_82",        "count": 20},
            {"item": "weapons.bombs.GBU_12",       "count": 8},
        ]

    def _friendly_cps(self):
        """Yields control points owned by this coalition."""
        is_player = self.coalition.player
        for cp in self.game.theater.controlpoints:
            # cp.captured is True when blue owns it
            if bool(cp.captured) == bool(is_player):
                yield cp

    def _find_cp_by_id(self, cp_id: int):
        for cp in self.game.theater.controlpoints:
            if cp.id == cp_id:
                return cp
        return None

    def _find_transport_squadron(self, exclude_cp):
        """
        Finds the nearest friendly CP (other than the destination) with
        a squadron capable of LOGISTIC missions that has aircraft available.
        Returns (ControlPoint, Squadron) or (None, None).
        """
        for cp in self._friendly_cps():
            if cp is exclude_cp:
                continue
            for squadron in getattr(cp, "squadrons", []):
                if FlightType.LOGISTIC in getattr(squadron, "mission_types", []):
                    if getattr(squadron, "has_available_aircraft", False):
                        return cp, squadron
        return None, None
