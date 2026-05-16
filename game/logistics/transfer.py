"""
game/logistics/transfer.py

A LogisticsTransfer represents one scheduled delivery between two
ControlPoints: a source warehouse (where stock is drawn) and a
destination warehouse (where it arrives on completion).

Lifecycle:
  PLANNED   → transfer is queued, stock reserved at source
  IN_FLIGHT → mission generated, aircraft en route
  DELIVERED → stock added to destination warehouse
  FAILED    → aircraft lost / drop zone not reached; reservation released

Transfers are created by the player in the Qt logistics panel or via
the REST API. On mission generation, each active PLANNED transfer spawns
a helicopter/transport flight via pydcs pointed at the drop zone.
On state.json processing after the mission, the result updates status.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .warehouse import WarehouseCategory


class TransferStatus(str, Enum):
    PLANNED   = "planned"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED    = "failed"


@dataclass
class LogisticsTransfer:
    """
    One logistics delivery between two control points.

    Attributes:
        transfer_id:   UUID, stable across saves.
        source_cp_id:  ControlPoint that supplies the cargo.
        dest_cp_id:    ControlPoint that receives the cargo.
        dz_id:         DropZone at destination where the aircraft lands/drops.
        category:      What is being delivered (FUEL, TROOPS, etc.).
        quantity:      How much is planned to be delivered.
        delivered:     How much was actually delivered (set on completion).
        status:        Current lifecycle state.
        aircraft_type: pydcs aircraft type string, e.g. "UH-1H" or "C-130".
        turn_planned:  Campaign turn when this was created.
        turn_resolved: Campaign turn when status became DELIVERED or FAILED.
        notes:         Optional player notes.
    """

    source_cp_id: int
    dest_cp_id: int
    dz_id: str
    category: WarehouseCategory
    quantity: float
    aircraft_type: str = "UH-1H"
    notes: str = ""
    transfer_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TransferStatus = TransferStatus.PLANNED
    delivered: float = 0.0
    turn_planned: int = 0
    turn_resolved: Optional[int] = None

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def mark_in_flight(self) -> None:
        """Call when the mission is generated and aircraft is spawned."""
        if self.status != TransferStatus.PLANNED:
            raise ValueError(f"Cannot mark in_flight from {self.status}")
        self.status = TransferStatus.IN_FLIGHT

    def mark_delivered(self, actual_quantity: float, turn: int) -> None:
        """
        Call when state.json confirms the drop zone was reached.
        actual_quantity may be less than planned (partial delivery).
        """
        self.status = TransferStatus.DELIVERED
        self.delivered = actual_quantity
        self.turn_resolved = turn

    def mark_failed(self, turn: int) -> None:
        """Call when aircraft was lost before reaching the drop zone."""
        self.status = TransferStatus.FAILED
        self.delivered = 0.0
        self.turn_resolved = turn

    @property
    def is_active(self) -> bool:
        return self.status in (TransferStatus.PLANNED, TransferStatus.IN_FLIGHT)

    @property
    def success_rate(self) -> Optional[float]:
        """Fraction delivered vs planned. None if not yet resolved."""
        if self.status not in (TransferStatus.DELIVERED, TransferStatus.FAILED):
            return None
        if self.quantity == 0:
            return 0.0
        return round(self.delivered / self.quantity, 3)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "transfer_id":   self.transfer_id,
            "source_cp_id":  self.source_cp_id,
            "dest_cp_id":    self.dest_cp_id,
            "dz_id":         self.dz_id,
            "category":      self.category.value,
            "quantity":      self.quantity,
            "delivered":     self.delivered,
            "status":        self.status.value,
            "aircraft_type": self.aircraft_type,
            "turn_planned":  self.turn_planned,
            "turn_resolved": self.turn_resolved,
            "notes":         self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticsTransfer":
        return cls(
            transfer_id=data["transfer_id"],
            source_cp_id=data["source_cp_id"],
            dest_cp_id=data["dest_cp_id"],
            dz_id=data["dz_id"],
            category=WarehouseCategory(data["category"]),
            quantity=data["quantity"],
            delivered=data.get("delivered", 0.0),
            status=TransferStatus(data["status"]),
            aircraft_type=data.get("aircraft_type", "UH-1H"),
            turn_planned=data.get("turn_planned", 0),
            turn_resolved=data.get("turn_resolved"),
            notes=data.get("notes", ""),
        )
