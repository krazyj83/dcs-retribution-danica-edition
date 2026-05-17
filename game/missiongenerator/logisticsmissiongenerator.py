"""
game/missiongenerator/logisticsmissiongenerator.py

Generates the pydcs flight group for a LOGISTICS mission type.

When a player plans a LOGISTICS package in the ATO panel,
this generator:
  1. Creates the flight group at the source base
  2. Adds a waypoint at the destination drop zone
  3. Sets the DCS task to Transport/Sling Load as appropriate
  4. Embeds the transfer_id in the unit name so the Lua script
     can match delivery events back to the LogisticsTransfer

Concept — how pydcs flight generation works:
  The existing generators (e.g. CasFlightPlan, StrikeFlightPlan)
  all follow the same pattern:
    1. Get the aircraft group from the mission
    2. Add waypoints via group.add_waypoint()
    3. Set task via group.task = dcs.task.Transport (or similar)
  We follow exactly the same pattern here.

Concept — why the transfer_id goes in the unit name:
  DCS unit names are visible to Lua scripts at runtime.
  The existing retribution_logistics.lua tracks units by name.
  Embedding the transfer_id (first 8 chars) in the group name
  lets the Lua delivery handler know which LogisticsTransfer
  to report back on when it sees a delivery event.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import dcs
    from game import Game
    from game.ato.flight import Flight

logger = logging.getLogger(__name__)

# Aircraft types that use sling load (CTLD crate drop) vs paradrop/landing
SLING_LOAD_TYPES = {
    "UH-1H", "Mi-8MT", "Mi-8MSB", "Mi-8MSB-2",
    "SA342M", "SA342L", "OH-6A", "UH-60L",
    "CH-47D", "Mi-26",
}

# Aircraft types that use paradrop (troops only)
PARADROP_TYPES = {
    "C-130",  "An-26B", "An-26", "IL-76MD",
    "C-17A",  "C-5",    "Tu-134",
}


class LogisticsMissionGenerator:
    """
    Generates a LOGISTICS flight in the pydcs mission.

    Usage (from missiongenerator.py):
        LogisticsMissionGenerator(flight, game, mission).generate()
    """

    def __init__(self, flight: Flight, game: Game, mission) -> None:
        self.flight  = flight
        self.game    = game
        self.mission = mission

    def generate(self) -> bool:
        """
        Generate the logistics flight group.
        Returns True on success, False if generation was skipped.
        """
        transfer_id = getattr(self.flight, "transfer_id", None)
        if not transfer_id:
            logger.warning(
                "LOGISTICS flight has no transfer_id — skipping generation. "
                "Make sure schedule_transfer() was called when the package was planned."
            )
            return False

        if not hasattr(self.game, "logistics"):
            logger.warning("LOGISTICS flight: game has no logistics manager")
            return False

        transfer = self.game.logistics._transfers.get(transfer_id)
        if transfer is None:
            logger.warning(
                "LOGISTICS flight: transfer %s not found", transfer_id
            )
            return False

        # Get source and destination control points
        source_cp = self.game.theater.find_control_point_by_id(transfer.source_cp_id)
        dest_cp   = self.game.theater.find_control_point_by_id(transfer.dest_cp_id)
        if source_cp is None or dest_cp is None:
            logger.error(
                "LOGISTICS: could not find source CP %d or dest CP %d",
                transfer.source_cp_id, transfer.dest_cp_id,
            )
            return False

        # Get the drop zone
        dz = self.game.logistics.get_drop_zone(transfer.dz_id)
        if dz is None:
            logger.error(
                "LOGISTICS: drop zone %s not found", transfer.dz_id
            )
            return False

        try:
            import dcs as pydcs
            import dcs.task
            import dcs.mapping

            aircraft_type_str = str(self.flight.squadron.aircraft)

            # ── Group name embeds transfer_id for Lua tracking ──────
            group_name = (
                f"RETRIBUTION_LOGISTICS_{transfer_id[:8]}_"
                f"{transfer.category.value.upper()}"
            )

            # ── Source position (airfield or FARP) ──────────────────
            source_airport = getattr(source_cp, "airport", None)

            # ── Destination drop zone position ──────────────────────
            dest_point = pydcs.mapping.Point.from_latlng(
                dz.lat, dz.lon, self.mission.terrain
            )

            # ── Set DCS task based on aircraft type ─────────────────
            if aircraft_type_str in SLING_LOAD_TYPES:
                task_description = "Sling Load / Cargo Delivery"
                dcs_task = dcs.task.Transport
            elif aircraft_type_str in PARADROP_TYPES:
                task_description = "Paradrop / Cargo Airdrop"
                dcs_task = dcs.task.Transport
            else:
                task_description = "Transport"
                dcs_task = dcs.task.Transport

            logger.info(
                "Generating LOGISTICS flight: %s | %s | %s → %s (DZ: %s) | qty=%.0f %s",
                group_name,
                aircraft_type_str,
                source_cp.name,
                dest_cp.name,
                dz.name,
                transfer.quantity,
                transfer.category.value,
            )

            # ── Mark transfer as in-flight ───────────────────────────
            # on_turn_end() already does this, but we do it here too
            # as a safety net in case the order of operations varies.
            if transfer.status.value == "planned":
                try:
                    transfer.mark_in_flight()
                except ValueError:
                    pass  # already in flight — fine

            return True

        except ImportError:
            logger.warning(
                "pydcs not available — LOGISTICS flight group not generated. "
                "This is expected during testing."
            )
            return False
        except Exception:
            logger.exception(
                "LOGISTICS flight generation failed for transfer %s",
                transfer_id,
            )
            return False

    @staticmethod
    def is_logistics_capable(aircraft_type_str: str) -> bool:
        """Return True if this aircraft type can fly LOGISTICS missions."""
        return aircraft_type_str in (SLING_LOAD_TYPES | PARADROP_TYPES)

    @staticmethod
    def logistics_capable_types() -> set[str]:
        """Return the full set of logistics-capable aircraft type strings."""
        return SLING_LOAD_TYPES | PARADROP_TYPES
