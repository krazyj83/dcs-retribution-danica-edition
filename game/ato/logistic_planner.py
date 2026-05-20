"""
game/ato/logistic_planner.py  — NEW FILE
=========================================
Auto-plans logistic resupply flights each turn for both coalitions.

Imports from game.logistics (your existing __init__.py) rather than
the supply_state.py we previously described — that file is not needed.
StockItem, WarehouseCategory, and LogisticsManager all already exist.

CONCEPT — where this fits in the turn sequence:
    1. Turn starts → ai_flight_planner.py runs for each coalition
    2. It calls LogisticPlanner.plan() here (one call per coalition)
    3. plan() reads the current StockItem levels from game.logistics
    4. For each base below threshold, it creates a Package + Flight
    5. Those packages go into the ATO alongside combat missions
    6. After the mission, debrief_hook.py credits the deliveries back
       into StockItem.quantity using apply_delivery()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from game.ato.flighttype import FlightType

if TYPE_CHECKING:
    from game.game import Game
    from game.coalition import Coalition
    from game.ato.package import Package
    from game.theater.controlpoint import ControlPoint
    from game.squadrons.squadron import Squadron

logger = logging.getLogger(__name__)


# ── Delivery amounts per flight (must match debrief_hook.py constants) ────────
# Keep these in sync with LOGISTIC_FUEL_DELIVERY / LOGISTIC_AMMO_DELIVERY
# in debrief_hook.py so the planner and hook agree on what one flight delivers.
FUEL_DELIVERY_PER_FLIGHT = 200.0
AMMO_DELIVERY_PER_FLIGHT = 150.0

# Turn consumption rates — subtracted from StockItem.quantity each turn
FUEL_CONSUMPTION_PER_TURN = 50.0   # tune: how fast bases burn fuel
AMMO_CONSUMPTION_PER_TURN = 80.0   # tune: ammo expended per turn of ops

# Max logistic flights per coalition per turn (prevent ATO flooding)
MAX_LOGISTIC_FLIGHTS = 3
# ─────────────────────────────────────────────────────────────────────────────


class LogisticPlanner:
    """
    Generates logistic resupply flights for one coalition per turn.

    Works identically for BLUEFOR and REDFOR — the coalition parameter
    scopes all CP lookups and squadron searches to the correct side.

    Usage (add to ai_flight_planner.py after the transport block):

        from game.ato.logistic_planner import LogisticPlanner

        planner = LogisticPlanner(game=self.game, coalition=self.coalition)
        for pkg in planner.plan():
            self.ato.add_package(pkg)
    """

    def __init__(self, game: "Game", coalition: "Coalition") -> None:
        self.game      = game
        self.coalition = coalition

        # game.logistics is the LogisticsManager from game/logistics/__init__.py
        self.logistics = getattr(game, "logistics", None)

    def plan(self) -> list["Package"]:
        """
        Main entry point. Returns new Package objects to add to the ATO.

        Steps:
          1. Apply turn consumption to all friendly CPs
          2. Find warehouses below resupply threshold (StockItem.needs_resupply)
          3. For each, find a transport squadron and create a Package + Flight
        """
        if self.logistics is None:
            logger.debug(
                f"[LogisticPlanner] {self._coalition_name}: "
                f"no logistics manager found, skipping."
            )
            return []

        self._apply_consumption()

        needy_cps = self._find_needy_cps()
        if not needy_cps:
            return []

        packages: list[Package] = []
        for dest_cp in needy_cps:
            if len(packages) >= MAX_LOGISTIC_FLIGHTS:
                break
            pkg = self._plan_resupply_to(dest_cp)
            if pkg is not None:
                packages.append(pkg)

        logger.info(
            f"[LogisticPlanner] {self._coalition_name}: "
            f"planned {len(packages)} logistic flight(s)."
        )
        return packages

    # ── Private helpers ───────────────────────────────────────────────────────

    @property
    def _coalition_name(self) -> str:
        try:
            return self.coalition.faction.name
        except Exception:
            return "Unknown"

    def _apply_consumption(self) -> None:
        """
        Subtract turn consumption from every friendly CP's warehouse.

        CONCEPT — why consume each turn:
            Without consumption the supply level never drops, so logistic
            flights are never triggered. Consumption simulates aircraft
            burning fuel on sorties and expending ammo each turn.
        """
        from game.logistics import WarehouseCategory

        for cp in self._friendly_cps():
            wh = self.logistics.get_warehouse(cp.id)
            if wh is None:
                continue
            wh.stock[WarehouseCategory.FUEL].apply_consumption(
                FUEL_CONSUMPTION_PER_TURN
            )
            wh.stock[WarehouseCategory.AMMUNITION].apply_consumption(
                AMMO_CONSUMPTION_PER_TURN
            )

    def _find_needy_cps(self) -> list["ControlPoint"]:
        """
        Returns friendly CPs whose fuel OR ammo StockItem is below threshold,
        sorted most-depleted first (lowest combined level = highest priority).
        """
        from game.logistics import WarehouseCategory

        needy = []
        for cp in self._friendly_cps():
            wh = self.logistics.get_warehouse(cp.id)
            if wh is None:
                continue
            fuel_item = wh.stock.get(WarehouseCategory.FUEL)
            ammo_item = wh.stock.get(WarehouseCategory.AMMUNITION)
            if fuel_item is None or ammo_item is None:
                continue
            if fuel_item.needs_resupply or ammo_item.needs_resupply:
                needy.append((cp, fuel_item.level + ammo_item.level))

        # Sort: lowest combined level first = most urgent
        needy.sort(key=lambda pair: pair[1])
        return [cp for cp, _ in needy]

    def _plan_resupply_to(self, dest_cp: "ControlPoint") -> Optional["Package"]:
        """Create one Package targeting dest_cp with a LOGISTIC flight."""
        # Avoid importing at module level to prevent circular imports
        from game.ato.package import Package
        from game.ato.flight import Flight

        origin_cp, squadron = self._find_transport_squadron(exclude_cp=dest_cp)
        if origin_cp is None or squadron is None:
            logger.debug(
                f"[LogisticPlanner] No transport squadron available "
                f"for resupply to {dest_cp.name}"
            )
            return None

        package = Package(target=dest_cp, auto_asap=True)

        flight = Flight(
            package=package,
            country=self.coalition.country,
            squadron=squadron,
            count=1,
            flight_type=FlightType.LOGISTIC,
            start_type="Warm",
        )

        # Attach payload so logistic_plugin_injector.py can read it
        # and build the Lua RETRIBUTION_LOGISTIC_MISSIONS table
        flight.logistic_payload = {
            "fuel_kg":          int(FUEL_DELIVERY_PER_FLIGHT * 250),  # kg equivalent
            "ammo_items":       self._ammo_items_for(dest_cp),
            "origin_base_name": getattr(origin_cp, "dcs_identifier", origin_cp.name),
            "dest_base_name":   getattr(dest_cp,   "dcs_identifier", dest_cp.name),
        }

        package.add_flight(flight)
        return package

    def _find_transport_squadron(
        self, exclude_cp: "ControlPoint"
    ) -> tuple[Optional["ControlPoint"], Optional["Squadron"]]:
        """
        Search all friendly CPs (except destination) for a squadron
        with FlightType.LOGISTIC in its allowed mission types.
        Returns (cp, squadron) or (None, None) if nothing is available.
        """
        for cp in self._friendly_cps():
            if cp is exclude_cp:
                continue
            for squadron in getattr(cp, "squadrons", []):
                if FlightType.LOGISTIC in getattr(squadron, "mission_types", []):
                    if getattr(squadron, "has_available_aircraft", False):
                        return cp, squadron
        return None, None

    def _friendly_cps(self) -> list["ControlPoint"]:
        """All control points owned by this coalition."""
        is_blue = self.coalition == self.game.blue
        return [
            cp for cp in self.game.theater.controlpoints
            if cp.captured == is_blue
        ]

    def _ammo_items_for(self, dest_cp: "ControlPoint") -> list[dict]:
        """
        Generic ammo load — enough to meaningfully resupply a base.
        Returns a list of {"item": str, "count": int} dicts for the Lua table.
        A future improvement could read the destination faction's preferred
        weapons and tailor the load accordingly.
        """
        wh = self.logistics.get_warehouse(dest_cp.id)
        if wh is None:
            return []

        from game.logistics import WarehouseCategory
        ammo_item = wh.stock.get(WarehouseCategory.AMMUNITION)
        if ammo_item is None or not ammo_item.needs_resupply:
            return []

        # Determine side to pick appropriate weapons
        is_blue = self.coalition == self.game.blue
        if is_blue:
            return [
                {"item": "weapons.missiles.AIM_120C", "count": 8},
                {"item": "weapons.missiles.AIM_9X",   "count": 8},
                {"item": "weapons.bombs.Mk_82",        "count": 20},
                {"item": "weapons.bombs.GBU_12",       "count": 8},
            ]
        else:
            return [
                {"item": "weapons.missiles.R_77",      "count": 8},
                {"item": "weapons.missiles.R_73",      "count": 8},
                {"item": "weapons.bombs.FAB_500M62",   "count": 20},
                {"item": "weapons.bombs.KAB_500Kr",    "count": 8},
            ]
