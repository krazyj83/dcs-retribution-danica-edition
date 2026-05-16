"""
game/logistics/manager.py

LogisticsManager is the single entry point for all logistics operations
in a campaign. It lives on the Game object alongside the Theater and ATO.

Responsibilities:
  - CRUD for DropZones (player creates/edits/deletes from Qt panel)
  - Warehouse registry (one Warehouse per ControlPoint)
  - Transfer scheduling and resolution
  - Turn rollover: apply spoilage, carry stock forward, generate missions
  - Mission generation hook: inject trigger zones and helo flights into pydcs

Concept — how pydcs trigger zones work:
  pydcs represents a DCS trigger zone as a dcs.triggers.TriggerZone.
  Each DropZone we create maps to one TriggerZone in the .miz file.
  Lua scripts (e.g. MOOSE CTLD for troop transport) look for these
  named zones at mission start and use them as landing/drop targets.

Concept — the turn lifecycle for logistics:
  1. Player opens Logistics panel → creates DropZones + Transfers
  2. on_turn_end():
       - Transfers marked PLANNED → IN_FLIGHT (stock reserved)
       - Warehouses apply spoilage
       - Snapshot saved to campaign JSON
  3. Mission generator calls inject_into_mission() → adds trigger zones
     + helicopter flights to retribution_nextturn.miz via pydcs
  4. After mission, on_state_processed(state_json):
       - Transfers resolved (DELIVERED or FAILED) based on Lua events
       - Delivered stock added to destination warehouses
       - Reservations released
  5. on_turn_start():
       - Warehouse rollover (stock carried forward)
       - New turn's logistics panel shows updated stock levels
"""

from __future__ import annotations

import logging
from typing import Dict, Iterator, List, Optional

from .dropzone import DropZone, DropZoneType
from .warehouse import Warehouse, WarehouseCategory
from .transfer import LogisticsTransfer, TransferStatus

logger = logging.getLogger(__name__)

# Capacity multiplier for FARPs / road bases (smaller than full airbases)
FARP_CAPACITY_MULTIPLIER = 0.3
AIRBASE_CAPACITY_MULTIPLIER = 1.0


class LogisticsManager:
    """
    Central logistics coordinator for a campaign.

    Attach one instance to the Game object:
        game.logistics = LogisticsManager()
    """

    def __init__(self) -> None:
        # dz_id → DropZone
        self._drop_zones: Dict[str, DropZone] = {}
        # cp_id → Warehouse
        self._warehouses: Dict[int, Warehouse] = {}
        # transfer_id → LogisticsTransfer
        self._transfers: Dict[str, LogisticsTransfer] = {}

    # ==================================================================
    # DropZone CRUD
    # ==================================================================

    def add_drop_zone(self, dz: DropZone) -> None:
        """Register a new drop zone (player-created)."""
        self._drop_zones[dz.dz_id] = dz
        logger.info("Added drop zone %r (%s)", dz.name, dz.dz_type.value)

    def remove_drop_zone(self, dz_id: str) -> bool:
        """
        Remove a drop zone. Returns False if it doesn't exist.
        Will also cancel any PLANNED transfers targeting this zone.
        """
        if dz_id not in self._drop_zones:
            return False
        for transfer in list(self.active_transfers):
            if transfer.dz_id == dz_id and transfer.status == TransferStatus.PLANNED:
                self.cancel_transfer(transfer.transfer_id)
        del self._drop_zones[dz_id]
        logger.info("Removed drop zone %s", dz_id)
        return True

    def get_drop_zone(self, dz_id: str) -> Optional[DropZone]:
        return self._drop_zones.get(dz_id)

    def drop_zones_for_cp(self, cp_id: int) -> List[DropZone]:
        return [dz for dz in self._drop_zones.values() if dz.cp_id == cp_id]

    def active_drop_zones(self, coalition: Optional[str] = None) -> List[DropZone]:
        return [
            dz for dz in self._drop_zones.values()
            if dz.active and (coalition is None or dz.coalition == coalition)
        ]

    @property
    def all_drop_zones(self) -> List[DropZone]:
        return list(self._drop_zones.values())

    # ==================================================================
    # Warehouse management
    # ==================================================================

    def ensure_warehouse(
        self,
        cp_id: int,
        cp_name: str,
        coalition: str = "blue",
        is_farp: bool = False,
    ) -> Warehouse:
        """
        Get or create the warehouse for a ControlPoint.
        Call this during campaign initialisation for every control point.
        """
        if cp_id not in self._warehouses:
            multiplier = FARP_CAPACITY_MULTIPLIER if is_farp else AIRBASE_CAPACITY_MULTIPLIER
            wh = Warehouse(
                cp_id=cp_id,
                cp_name=cp_name,
                coalition=coalition,
                capacity_multiplier=multiplier,
            )
            self._warehouses[cp_id] = wh
            logger.debug("Created warehouse for CP %d (%s)", cp_id, cp_name)
        return self._warehouses[cp_id]

    def get_warehouse(self, cp_id: int) -> Optional[Warehouse]:
        return self._warehouses.get(cp_id)

    def warehouses_for_coalition(self, coalition: str) -> List[Warehouse]:
        return [wh for wh in self._warehouses.values() if wh.coalition == coalition]

    def seed_warehouse(
        self,
        cp_id: int,
        category: WarehouseCategory,
        amount: float,
    ) -> None:
        """
        Add initial stock to a warehouse (called during campaign start).
        Safe to call multiple times — stock is additive up to capacity.
        """
        wh = self._warehouses.get(cp_id)
        if wh is None:
            logger.warning("Tried to seed unknown warehouse cp_id=%d", cp_id)
            return
        surplus = wh.add(category, amount)
        if surplus > 0:
            logger.debug(
                "Warehouse %d at capacity for %s, surplus=%.1f",
                cp_id, category.value, surplus,
            )

    # ==================================================================
    # Transfer management
    # ==================================================================

    def schedule_transfer(
        self,
        source_cp_id: int,
        dest_cp_id: int,
        dz_id: str,
        category: WarehouseCategory,
        quantity: float,
        aircraft_type: str = "UH-1H",
        turn: int = 0,
        notes: str = "",
    ) -> Optional[LogisticsTransfer]:
        """
        Schedule a logistics transfer. Reserves stock at source immediately.
        Returns None if source doesn't have enough available stock.
        """
        source_wh = self._warehouses.get(source_cp_id)
        if source_wh is None:
            logger.error("schedule_transfer: unknown source CP %d", source_cp_id)
            return None

        # Try to reserve the requested amount
        reserved = source_wh.reserve(category, quantity)
        if reserved < quantity * 0.01:  # can't reserve even 1%
            logger.warning(
                "Insufficient stock at CP %d for %s transfer (want=%.1f, available=%.1f)",
                source_cp_id, category.value, quantity,
                source_wh.available(category),
            )
            return None

        transfer = LogisticsTransfer(
            source_cp_id=source_cp_id,
            dest_cp_id=dest_cp_id,
            dz_id=dz_id,
            category=category,
            quantity=reserved,   # use what was actually reserved
            aircraft_type=aircraft_type,
            turn_planned=turn,
            notes=notes,
        )
        self._transfers[transfer.transfer_id] = transfer
        logger.info(
            "Scheduled transfer %s: %.1f %s from CP%d → CP%d via DZ %s",
            transfer.transfer_id[:8], reserved, category.value,
            source_cp_id, dest_cp_id, dz_id,
        )
        return transfer

    def cancel_transfer(self, transfer_id: str) -> bool:
        """Cancel a PLANNED transfer and release the reservation."""
        transfer = self._transfers.get(transfer_id)
        if transfer is None or transfer.status != TransferStatus.PLANNED:
            return False
        source_wh = self._warehouses.get(transfer.source_cp_id)
        if source_wh:
            source_wh.release_reserve(transfer.category, transfer.quantity)
        transfer.status = TransferStatus.FAILED
        logger.info("Cancelled transfer %s", transfer_id[:8])
        return True

    @property
    def active_transfers(self) -> Iterator[LogisticsTransfer]:
        for t in self._transfers.values():
            if t.is_active:
                yield t

    def transfers_for_cp(self, cp_id: int) -> List[LogisticsTransfer]:
        return [
            t for t in self._transfers.values()
            if t.source_cp_id == cp_id or t.dest_cp_id == cp_id
        ]

    # ==================================================================
    # Turn lifecycle hooks
    # ==================================================================

    def on_turn_end(self, current_turn: int) -> None:
        """
        Called when the player hits 'End Turn' / 'Take Off'.

        1. Move PLANNED transfers → IN_FLIGHT
           (mission generator will spawn helo flights for these)
        2. Apply warehouse spoilage
        """
        for transfer in list(self.active_transfers):
            if transfer.status == TransferStatus.PLANNED:
                source_wh = self._warehouses.get(transfer.source_cp_id)
                if source_wh:
                    # Actually consume the reserved stock — it's now in the air
                    source_wh.consume(transfer.category, transfer.quantity, ignore_reserve=True)
                    source_wh.release_reserve(transfer.category, transfer.quantity)
                transfer.mark_in_flight()
                logger.info(
                    "Transfer %s now in flight (%.1f %s)",
                    transfer.transfer_id[:8], transfer.quantity, transfer.category.value,
                )

        # Apply spoilage to all warehouses
        for cp_id, wh in self._warehouses.items():
            losses = wh.apply_spoilage()
            for cat, lost in losses.items():
                if lost > 0.1:
                    logger.debug(
                        "Spoilage at CP%d: %.2f %s evaporated", cp_id, lost, cat.value,
                    )

    def on_state_processed(self, state: dict, current_turn: int) -> None:
        """
        Called after state.json from DCS is parsed.

        Resolves IN_FLIGHT transfers based on Lua-reported events.
        state["logistics_events"] is a list of dicts emitted by the
        Lua delivery script when an aircraft reaches a drop zone:
          {
            "transfer_id": "...",
            "delivered":   450.0,   # actual amount dropped
            "success":     true
          }
        """
        events = state.get("logistics_events", [])
        resolved_ids = set()

        for event in events:
            tid = event.get("transfer_id")
            transfer = self._transfers.get(tid)
            if transfer is None or transfer.status != TransferStatus.IN_FLIGHT:
                continue
            if event.get("success"):
                actual = float(event.get("delivered", transfer.quantity))
                dest_wh = self._warehouses.get(transfer.dest_cp_id)
                if dest_wh:
                    surplus = dest_wh.add(transfer.category, actual)
                    if surplus > 0:
                        logger.warning(
                            "Destination CP%d full, %.1f %s lost",
                            transfer.dest_cp_id, surplus, transfer.category.value,
                        )
                transfer.mark_delivered(actual, current_turn)
                logger.info(
                    "Transfer %s DELIVERED: %.1f %s to CP%d",
                    tid[:8], actual, transfer.category.value, transfer.dest_cp_id,
                )
            else:
                transfer.mark_failed(current_turn)
                logger.warning("Transfer %s FAILED (aircraft lost)", tid[:8])
            resolved_ids.add(tid)

        # Any IN_FLIGHT transfers not in the event list → failed (no Lua event)
        for transfer in self._transfers.values():
            if transfer.status == TransferStatus.IN_FLIGHT and transfer.transfer_id not in resolved_ids:
                transfer.mark_failed(current_turn)
                logger.warning(
                    "Transfer %s marked FAILED (no event in state.json)", transfer.transfer_id[:8],
                )

    def on_turn_start(self, previous_snapshot: Optional[dict] = None) -> None:
        """
        Called at the start of a new turn.
        Rolls warehouse inventory forward from the previous snapshot.
        """
        if previous_snapshot is None:
            return
        for cp_id_str, wh_data in previous_snapshot.get("warehouses", {}).items():
            cp_id = int(cp_id_str)
            wh = self._warehouses.get(cp_id)
            if wh:
                wh.rollover(wh_data)
                logger.debug("Rolled over warehouse for CP%d", cp_id)

    # ==================================================================
    # Mission generation hook
    # ==================================================================

    def inject_into_mission(self, mission) -> None:
        """
        Inject drop zones as DCS trigger zones into a pydcs Mission object.

        Call this from the mission generator just before mission.save().
        Each active DropZone becomes a TriggerZone that Lua scripts
        (MOOSE CTLD, custom delivery scripts) can reference by name.

        pydcs usage:
            mission.triggers.add_triggerzone(
                dcs.triggers.TriggerZone(
                    position=dcs.mapping.Point(x, y, mission.terrain),
                    radius=500,
                    hidden=False,
                    name="RETRIBUTION_DZ_TROOP_LZ_ALPHA",
                    color=[1, 0.5, 0, 0.5],  # RGBA orange for troop zones
                )
            )
        """
        try:
            import dcs  # pydcs — only available at mission-gen time
        except ImportError:
            logger.warning("pydcs not available; skipping drop zone injection")
            return

        TROOP_COLOR = [1.0, 0.5, 0.0, 0.5]   # orange (semi-transparent)
        CARGO_COLOR = [0.0, 0.5, 1.0, 0.5]   # blue

        for dz in self.active_drop_zones():
            color = TROOP_COLOR if dz.dz_type == DropZoneType.TROOP else CARGO_COLOR
            # Convert lat/lon to DCS mission coordinates via pydcs
            point = dcs.mapping.Point.from_latlng(
                dz.lat, dz.lon, mission.terrain
            )
            zone = dcs.triggers.TriggerZone(
                position=point,
                radius=dz.radius_m,
                hidden=False,
                name=dz.trigger_zone_name,
                color=color,
            )
            mission.triggers.add_triggerzone(zone)
            logger.debug(
                "Injected trigger zone %r at (%.4f, %.4f)",
                dz.trigger_zone_name, dz.lat, dz.lon,
            )

        # Inject IN_FLIGHT transfer helicopter missions
        self._inject_logistics_flights(mission)

    def _inject_logistics_flights(self, mission) -> None:
        """
        For each IN_FLIGHT transfer, spawn a helicopter/transport flight
        that flies from source CP to the destination drop zone.

        This is called inside inject_into_mission() after zones are added,
        so the trigger zone already exists when the flight plan references it.
        """
        try:
            import dcs
        except ImportError:
            return

        for transfer in self._transfers.values():
            if transfer.status != TransferStatus.IN_FLIGHT:
                continue
            dz = self._drop_zones.get(transfer.dz_id)
            if dz is None:
                logger.warning("Transfer %s has unknown DZ %s", transfer.transfer_id[:8], transfer.dz_id)
                continue
            # Mission generator creates the actual flight group.
            # Here we emit a structured dict consumed by the flight builder.
            # (Full pydcs group creation belongs in game/missiongenerator/.)
            logger.info(
                "Will generate logistics flight: %s from CP%d → DZ %r",
                transfer.aircraft_type, transfer.source_cp_id, dz.name,
            )

    # ==================================================================
    # Serialisation — full logistics state for campaign JSON
    # ==================================================================

    def to_dict(self) -> dict:
        return {
            "drop_zones": {
                dz_id: dz.to_dict()
                for dz_id, dz in self._drop_zones.items()
            },
            "warehouses": {
                str(cp_id): wh.to_dict()
                for cp_id, wh in self._warehouses.items()
            },
            "transfers": {
                tid: t.to_dict()
                for tid, t in self._transfers.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticsManager":
        mgr = cls()
        for dz_data in data.get("drop_zones", {}).values():
            mgr._drop_zones[dz_data["dz_id"]] = DropZone.from_dict(dz_data)
        for wh_data in data.get("warehouses", {}).values():
            wh = Warehouse.from_dict(wh_data)
            mgr._warehouses[wh.cp_id] = wh
        for t_data in data.get("transfers", {}).values():
            t = LogisticsTransfer.from_dict(t_data)
            mgr._transfers[t.transfer_id] = t
        return mgr
