"""
game/ato/flightplans/logistic.py

Flight plan for a LOGISTIC warehouse-resupply mission.

Route shape is identical to AirliftFlightPlan:
  Depart -> Pickup (source warehouse) -> Dropoff (destination) -> RTB

The difference is where the stops come from. An airlift reads them from
``flight.cargo``, a unit TransferOrder. A LOGISTIC flight carries supplies, not
units, so it must NOT set ``flight.cargo`` (that would register it as a unit
airlift and the results processor would try to move ground units). Instead the
flight carries ``flight.transfer_id``, and the stops come from that warehouse
transfer: its source base and destination base.

A flight planned to a player drop zone delivers there instead of landing at
the base: the drop zone belongs to a friendly base (the transfer's
destination), and crates set down inside it count as delivered to that base.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

from dcs import Point

from game.ato.flightplans.airlift import (
    AirliftFlightPlan,
    Builder as AirliftBuilder,
    CargoStops,
)
from game.ato.flightplans.planningerror import PlanningError

if TYPE_CHECKING:
    from game.theater import ControlPoint
    from game.theater.missiontarget import MissionTarget


@dataclass(frozen=True)
class LogisticStops:
    origin: ControlPoint
    #: The destination base, or the drop zone the flight delivers to.
    next_stop: MissionTarget


class Builder(AirliftBuilder):
    def cargo_stops(self) -> CargoStops:
        game = self.flight.coalition.game
        transfer_id = self.flight.transfer_id
        if transfer_id is None:
            # Planned by hand in the mission planner: the flight gets an empty
            # transfer (pickup = its own base, delivery = the package target)
            # and the cargo is chosen in its Cargo tab.
            from game.logistics.flight_cargo import attach_transfer

            transfer_id = attach_transfer(game, self.flight).transfer_id
        transfer = game.logistics._transfers.get(transfer_id)
        if transfer is None:
            raise PlanningError(f"Warehouse transfer {transfer_id} not found.")
        try:
            origin = game.theater.find_control_point_by_id(transfer.source_cp_id)
            destination = game.theater.find_control_point_by_id(transfer.dest_cp_id)
        except KeyError as ex:
            raise PlanningError(str(ex)) from ex
        from game.logistics.custom_airdrop import CustomAirdropTarget

        target = self.flight.package.target
        if isinstance(target, CustomAirdropTarget) and transfer.dz_id:
            return LogisticStops(origin, target)
        return LogisticStops(origin, destination)

    # Helicopter airlifts add CTLD pickup/drop-off zones, which only exist at
    # CTLD-capable points. Supplies are loaded and unloaded at the bases.
    def _generate_ctld_pickup(self) -> Point:
        return self.cargo_stops().origin.position

    def _generate_ctld_dropoff(self) -> Point:
        return self.cargo_stops().next_stop.position

    def build(self, dump_debug_info: bool = False) -> LogisticFlightPlan:
        return LogisticFlightPlan(self.flight, self.layout())


class LogisticFlightPlan(AirliftFlightPlan):
    """Flight plan for a LOGISTIC resupply mission (see module docstring)."""

    @staticmethod
    def builder_type() -> Type[Builder]:
        return Builder
