"""LOGISTIC flights that carry warehouse transfers.

A scheduled warehouse transfer is only delivered if a real LOGISTIC flight
carries it. This module plans that flight (nearest free transport squadron to
the source base, one aircraft), finds it again later, and removes it when the
transfer is cancelled. Settlement after the mission lives in
``LogisticsManager.on_state_processed``.

Modelled on Retribution's own ``AirliftPlanner.create_package_for_airlift``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from game.ato.flight import Flight
from game.ato.flighttype import FlightType
from game.ato.flightplans.planningerror import PlanningError
from game.ato.package import Package
from game.theater.player import Player

if TYPE_CHECKING:
    from game import Game
    from game.logistics import LogisticsTransfer
    from game.squadrons import Squadron
    from game.theater import ControlPoint

logger = logging.getLogger(__name__)


def control_point(game: Game, cp_id: object) -> Optional[ControlPoint]:
    """Warehouse ids are ControlPoint ids (UUIDs, despite the int annotations)."""
    try:
        return game.theater.find_control_point_by_id(cp_id)  # type: ignore[arg-type]
    except KeyError:
        return None


def flight_for_transfer(game: Game, transfer_id: str) -> Optional[Flight]:
    for package in game.blue.ato.packages:
        for flight in package.flights:
            if flight.transfer_id == transfer_id:
                return flight
    return None


def find_transport_squadron(game: Game, source: ControlPoint) -> Optional[Squadron]:
    """The free LOGISTIC-capable blue squadron based nearest the source base."""
    candidates = [
        squadron
        for squadron in game.blue.air_wing.iter_squadrons()
        if squadron.capable_of(FlightType.LOGISTIC)
        and squadron.location.captured is Player.BLUE
        and squadron.can_fulfill_flight(1)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: s.location.position.distance_to_point(source.position),
    )


def plan_transfer_flight(
    game: Game, transfer: LogisticsTransfer, now: datetime
) -> Optional[Flight]:
    """Create (or return the existing) LOGISTIC flight for a warehouse transfer.

    Returns None when the transfer cannot be flown right now: no free transport
    aircraft, a base is no longer friendly, or the route could not be planned.
    The transfer then stays PLANNED and is retried at the start of next turn.
    """
    existing = flight_for_transfer(game, transfer.transfer_id)
    if existing is not None:
        return existing

    source = control_point(game, transfer.source_cp_id)
    destination = control_point(game, transfer.dest_cp_id)
    if source is None or destination is None:
        return None
    if source.captured is not Player.BLUE or destination.captured is not Player.BLUE:
        return None

    squadron = find_transport_squadron(game, source)
    if squadron is None:
        logger.info(
            "Warehouse transfer %s: no free transport aircraft; retrying next turn",
            transfer.transfer_id[:8],
        )
        return None

    start_type = squadron.location.required_aircraft_start_type
    if start_type is None:
        start_type = game.settings.default_start_type

    package = Package(destination, game.db.flights, auto_asap=True)
    flight = Flight(package, squadron, 1, FlightType.LOGISTIC, start_type, divert=None)
    flight.transfer_id = transfer.transfer_id
    package.add_flight(flight)
    try:
        flight.recreate_flight_plan()
    except PlanningError:
        logger.exception(
            "Warehouse transfer %s: could not plan the LOGISTIC flight",
            transfer.transfer_id[:8],
        )
        package.remove_flight(flight)  # returns the aircraft and pilot
        return None

    package.set_tot_asap(now)
    game.blue.ato.add_package(package)
    transfer.aircraft_type = str(squadron.aircraft)

    from game.server import EventStream
    from game.sim import GameUpdateEvents

    EventStream.put_nowait(GameUpdateEvents().new_flight(flight))
    logger.info(
        "Warehouse transfer %s: %s from %s carries %s -> %s",
        transfer.transfer_id[:8],
        squadron.aircraft,
        squadron.location.name,
        source.name,
        destination.name,
    )
    return flight


def remove_transfer_flight(game: Game, transfer_id: str) -> bool:
    """Remove a cancelled transfer's flight (and its package if now empty)."""
    flight = flight_for_transfer(game, transfer_id)
    if flight is None:
        return False
    package = flight.package
    package.remove_flight(flight)
    if not package.flights:
        game.blue.ato.remove_package(package)

    from game.server import EventStream
    from game.sim import GameUpdateEvents

    EventStream.put_nowait(GameUpdateEvents().delete_flight(flight))
    return True


def plan_pending_transfer_flights(game: Game, now: datetime) -> None:
    """Give every unsettled warehouse transfer a flight in this turn's ATO.

    Runs at the start of the blue turn, before the AI plans its own missions, so
    warehouse transfers get first call on transport aircraft. Transfers left
    IN_FLIGHT by a mission whose results were never processed go back to
    PLANNED and are flown again.
    """
    from game.logistics import TransferStatus

    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return
    for transfer in list(logistics._transfers.values()):
        if transfer.status is TransferStatus.IN_FLIGHT:
            transfer.status = TransferStatus.PLANNED
        if transfer.status is TransferStatus.PLANNED:
            plan_transfer_flight(game, transfer, now)
