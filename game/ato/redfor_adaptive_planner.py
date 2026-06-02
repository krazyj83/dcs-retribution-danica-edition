"""
game/ato/redfor_adaptive_planner.py

Observes BLUEFOR mission patterns over the last N turns and adjusts
REDFOR priorities to counter the player's strategy.

Pattern → REDFOR response:
  SEAD/DEAD heavy   → Procurement requests for more SAM units
  BAI heavy         → Convoys include SHORAD units; more ground escorts
  OCA heavy         → Procurement requests for more interceptors
  CAS heavy         → More armor sent to frontline bases
  TRANSPORT heavy   → Procurement requests for fighters to intercept

Wired in game/game.py finish_turn():
    1. RedforAdaptivePlanner(self).observe()   ← snapshots BLUEFOR ATO
    2. RedforAdaptivePlanner(self).adapt()     ← adjusts REDFOR priorities
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.game import Game

logger = logging.getLogger(__name__)

# How many of a mission type in the window triggers a response
THRESHOLD_LOW  = 2   # subtle adjustment
THRESHOLD_HIGH = 4   # strong adjustment


class RedforAdaptivePlanner:
    """Adapts REDFOR behaviour based on observed BLUEFOR mission patterns.

    Call observe() first (while BLUEFOR ATO is still populated) then
    adapt() (after REDFOR end_turn processing is complete).
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        self.red = game.red
        # Ensure the history object exists (migration safety)
        if not hasattr(game, "bluefor_mission_history"):
            from game.models.game_stats import BlueforMissionHistory
            game.bluefor_mission_history = BlueforMissionHistory()
        self.history = game.bluefor_mission_history

    # ── Observation ───────────────────────────────────────────────────────────

    def observe(self) -> None:
        """Snapshot BLUEFOR ATO before it is cleared for the next turn.

        Must be called while game.blue.ato is still populated (i.e. before
        initialize_turn clears it).
        """
        self.history.record(self.game.blue.ato, self.game.turn)
        counts = self.history.total_counts()
        if counts:
            top = sorted(counts.items(), key=lambda x: -x[1])[:3]
            summary = ", ".join(f"{ft.value}×{n}" for ft, n in top)
            logger.info(
                "RedforAdaptivePlanner: BLUEFOR pattern (last %d turns): %s",
                self.history.turns_recorded, summary,
            )

    # ── Adaptation ────────────────────────────────────────────────────────────

    def adapt(self) -> None:
        """Apply REDFOR counter-strategy based on recorded BLUEFOR patterns."""
        if not self.history.has_turns():
            return
        if not self._is_enabled():
            return

        from game.ato.flighttype import FlightType

        counts = self.history.total_counts()

        # SEAD/DEAD heavy → reinforce SAM coverage
        sead_count = counts.get(FlightType.SEAD, 0) + counts.get(FlightType.DEAD, 0)
        if sead_count >= THRESHOLD_LOW:
            self._counter_sead(sead_count)

        # BAI heavy → protect convoys with SHORAD
        bai_count = counts.get(FlightType.BAI, 0)
        if bai_count >= THRESHOLD_LOW:
            self._counter_bai(bai_count)

        # OCA heavy → reinforce air defenses at airfields
        oca_count = (
            counts.get(FlightType.OCA_AIRCRAFT, 0)
            + counts.get(FlightType.OCA_RUNWAY, 0)
        )
        if oca_count >= THRESHOLD_LOW:
            self._counter_oca(oca_count)

        # CAS heavy → send more armor to frontline
        cas_count = counts.get(FlightType.CAS, 0)
        if cas_count >= THRESHOLD_LOW:
            self._counter_cas(cas_count)

        # TRANSPORT/LOGISTIC heavy → intercept supply corridors
        transport_count = (
            counts.get(FlightType.TRANSPORT, 0)
            + counts.get(getattr(FlightType, "LOGISTIC", None), 0)
            if hasattr(FlightType, "LOGISTIC") else
            counts.get(FlightType.TRANSPORT, 0)
        )
        if transport_count >= THRESHOLD_LOW:
            self._counter_transport(transport_count)

    # ── Counter-strategies ────────────────────────────────────────────────────

    def _counter_sead(self, count: int) -> None:
        """REDFOR detects heavy SEAD activity → requests more SAM units."""
        from game.procurement import GroundUnitProcurementRequest
        from game.data.units import UnitClass

        strength = "heavy" if count >= THRESHOLD_HIGH else "moderate"
        logger.info(
            "RedforAdaptivePlanner: %s SEAD detected (%d) → reinforcing SAM coverage",
            strength, count,
        )

        # Find frontline red CPs and request SAM replenishment
        requested = 0
        for cp in self.game.theater.controlpoints:
            if cp.captured or not cp.has_active_frontline:
                continue
            if requested >= 2:
                break
            try:
                self.red.procurement_requests.add(
                    GroundUnitProcurementRequest(cp, [UnitClass.SHORAD], 1)
                )
                requested += 1
                logger.debug(
                    "RedforAdaptivePlanner: requested SHORAD unit at %s", cp.name
                )
            except Exception as e:
                logger.debug("RedforAdaptivePlanner: SHORAD request failed: %s", e)

    def _counter_bai(self, count: int) -> None:
        """REDFOR detects heavy BAI → signals convoy planner to add SHORAD escort."""
        strength = "heavy" if count >= THRESHOLD_HIGH else "moderate"
        logger.info(
            "RedforAdaptivePlanner: %s BAI detected (%d) → flagging convoy SHORAD escort",
            strength, count,
        )
        # Set a flag on the game object that RedforSupplyPlanner reads
        self.game.redfor_convoy_shorad_escort = True

    def _counter_oca(self, count: int) -> None:
        """REDFOR detects heavy OCA → requests interceptors at threatened airbases."""
        from game.procurement import AircraftProcurementRequest
        from game.ato.flighttype import FlightType

        strength = "heavy" if count >= THRESHOLD_HIGH else "moderate"
        logger.info(
            "RedforAdaptivePlanner: %s OCA detected (%d) → requesting interceptors",
            strength, count,
        )

        # Find red airbases with squadrons and request fighter replenishment
        requested = 0
        for cp in self.game.theater.controlpoints:
            if cp.captured or requested >= 2:
                continue
            if not hasattr(cp, "squadrons"):
                continue
            for squadron in cp.squadrons:
                if squadron.can_auto_assign(FlightType.BARCAP):
                    try:
                        self.red.procurement_requests.add(
                            AircraftProcurementRequest(cp, FlightType.BARCAP, 2)
                        )
                        requested += 1
                        logger.debug(
                            "RedforAdaptivePlanner: requested BARCAP aircraft at %s",
                            cp.name,
                        )
                        break
                    except Exception as e:
                        logger.debug(
                            "RedforAdaptivePlanner: BARCAP request failed: %s", e
                        )

    def _counter_cas(self, count: int) -> None:
        """REDFOR detects heavy CAS → sends more armor to frontline bases."""
        from game.transfers import TransferOrder
        from datetime import datetime

        strength = "heavy" if count >= THRESHOLD_HIGH else "moderate"
        logger.info(
            "RedforAdaptivePlanner: %s CAS detected (%d) → reinforcing frontline armor",
            strength, count,
        )

        now = datetime.utcnow()
        reinforced = 0

        for cp in self.game.theater.controlpoints:
            if cp.captured or reinforced >= 2:
                continue
            if not cp.has_active_frontline:
                continue
            if not hasattr(cp, "base") or not hasattr(cp.base, "armor"):
                continue

            # Find a rear base to send armor from
            for source in self.game.theater.controlpoints:
                if source.captured or source is cp:
                    continue
                if not hasattr(source, "base") or source.base.total_armor < 4:
                    continue
                # Only send from non-frontline rear bases
                if source.has_active_frontline:
                    continue

                units = {}
                for unit_type, available in source.base.armor.items():
                    send = min(available // 3, 2)
                    if send > 0:
                        units[unit_type] = send
                    if sum(units.values()) >= 2:
                        break

                if not units:
                    continue

                try:
                    transfer = TransferOrder(source, cp, units)
                    self.red.transfers.new_transfer(transfer, now)
                    reinforced += 1
                    logger.info(
                        "RedforAdaptivePlanner: reinforcing frontline %s from %s (%d units)",
                        cp.name, source.name, sum(units.values()),
                    )
                    break
                except Exception as e:
                    logger.debug(
                        "RedforAdaptivePlanner: frontline reinforcement failed: %s", e
                    )

    def _counter_transport(self, count: int) -> None:
        """REDFOR detects heavy TRANSPORT → requests fighters to contest supply corridors."""
        from game.procurement import AircraftProcurementRequest
        from game.ato.flighttype import FlightType

        strength = "heavy" if count >= THRESHOLD_HIGH else "moderate"
        logger.info(
            "RedforAdaptivePlanner: %s TRANSPORT detected (%d) → contesting supply corridors",
            strength, count,
        )

        requested = 0
        for cp in self.game.theater.controlpoints:
            if cp.captured or requested >= 1:
                continue
            if not hasattr(cp, "squadrons"):
                continue
            for squadron in cp.squadrons:
                if squadron.can_auto_assign(FlightType.TARCAP):
                    try:
                        self.red.procurement_requests.add(
                            AircraftProcurementRequest(cp, FlightType.TARCAP, 2)
                        )
                        requested += 1
                        logger.debug(
                            "RedforAdaptivePlanner: requested TARCAP aircraft at %s",
                            cp.name,
                        )
                        break
                    except Exception as e:
                        logger.debug(
                            "RedforAdaptivePlanner: TARCAP request failed: %s", e
                        )

    def _is_enabled(self) -> bool:
        settings = getattr(self.game, "settings", None)
        if settings is None:
            return True
        return getattr(settings, "redfor_resupply_enabled", True)
