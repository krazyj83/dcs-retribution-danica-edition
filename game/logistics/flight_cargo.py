"""Cargo planned as part of a LOGISTIC flight in the mission planner.

Every BLUEFOR LOGISTIC flight carries one weapon transfer (``flight.transfer_id``):

- created empty when the flight is first planned: pickup = the squadron's base,
  delivery = the package's target base;
- filled in the flight's Cargo tab (weapons leave the pickup base's stock as
  they are loaded, and go back when unloaded);
- released (cargo back to stock) when the flight or its package is deleted.

The mission then places the cargo next to the aircraft and prints a load sheet
on the kneeboard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from game.ato.flightplans.planningerror import PlanningError
from game.theater.player import Player

if TYPE_CHECKING:
    from game import Game
    from game.ato.flight import Flight
    from game.logistics import LogisticsTransfer
    from game.theater import ControlPoint


def transfer_for_flight(game: Game, flight: Flight) -> Optional[LogisticsTransfer]:
    logistics = getattr(game, "logistics", None)
    transfer_id = getattr(flight, "transfer_id", None)
    if logistics is None or not transfer_id:
        return None
    return logistics._transfers.get(transfer_id)


def fuel_fraction(flight: Flight) -> float:
    fuel_max = float(flight.unit_type.dcs_unit_type.fuel_max or 0)
    return float(flight.fuel) / fuel_max if fuel_max > 0 else 1.0


def sync_transfer(transfer: LogisticsTransfer, flight: Flight) -> None:
    """Keep the transfer's squadron, aircraft and fuel in step with the flight."""
    transfer.squadron = flight.squadron
    transfer.aircraft_type = str(flight.unit_type)
    transfer.fuel_fraction = fuel_fraction(flight)


def attach_transfer(game: Game, flight: Flight) -> LogisticsTransfer:
    """The flight's transfer, created (empty) on first use.

    Raises PlanningError when the flight can't carry a transfer: not BLUEFOR,
    or the package target is not a friendly base.
    """
    from game.theater import ControlPoint

    existing = transfer_for_flight(game, flight)
    if existing is not None:
        return existing
    logistics = getattr(game, "logistics", None)
    if logistics is None:
        raise PlanningError("This campaign has no logistics system.")
    if flight.squadron.player is not Player.BLUE:
        raise PlanningError("Only BLUEFOR plans LOGISTIC flights by hand.")
    destination = flight.package.target
    if (
        not isinstance(destination, ControlPoint)
        or destination.captured is not Player.BLUE
    ):
        raise PlanningError("A LOGISTIC flight must deliver to a friendly base.")
    drop_zones = [dz for dz in logistics.drop_zones_for_cp(destination.id) if dz.active]
    transfer = logistics.create_flight_transfer(
        source_cp_id=flight.departure.id,
        dest_cp_id=destination.id,
        dz_id=drop_zones[0].dz_id if drop_zones else "",
        aircraft_type=str(flight.unit_type),
        turn=game.turn,
    )
    sync_transfer(transfer, flight)
    flight.transfer_id = transfer.transfer_id
    return transfer


def pickup_bases(game: Game, flight: Flight) -> List[ControlPoint]:
    """Friendly bases the flight can load at: its own base first, then nearest."""
    home = flight.departure
    others = [
        cp
        for cp in game.theater.controlpoints
        if cp is not home
        and cp.captured is Player.BLUE
        and not cp.is_fleet
        and cp.can_operate(flight.unit_type)
    ]
    others.sort(key=lambda cp: cp.position.distance_to_point(home.position))
    return [home, *others]


def release_flight_transfer(game: Game, flight: Flight) -> bool:
    """Flight deleted before it flew: cargo back to the pickup base's stock."""
    transfer = transfer_for_flight(game, flight)
    if transfer is None:
        return False
    return bool(game.logistics.cancel_transfer(transfer.transfer_id))
