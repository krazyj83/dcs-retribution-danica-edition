"""
game/ato/redfor_supply_planner.py

Each turn, moves REDFOR ground units from bases with more than their target to
bases below it: frontline bases first, nearest supplier first (see
RedforSupplyPlanner). The transport depends on distance, using the shared bands
in game/logistics/transport_tiers.py:
  - Under 120 km, road-connected -> land convoy (visible, targetable)
  - Under 220 km                 -> airlift, helicopters preferred
  - Over 220 km                  -> airlift, planes preferred
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from game.game import Game
    from game.dcs.groundunittype import GroundUnitType
    from game.theater import ControlPoint

logger = logging.getLogger(__name__)

CONVOY_SIZE = 4
MAX_CONVOYS_PER_TURN = 3


def has_transfer_route(
    game: Game, origin: ControlPoint, destination: ControlPoint
) -> bool:
    """True if origin's coalition can route a ground transfer to destination.

    PendingTransfers.new_transfer() removes the units from the origin base
    *before* it looks for a route, so a transfer with no route loses those
    units and leaves a broken pending transfer behind. Always check first.
    """
    network = game.transit_network_for(origin.captured)
    if origin not in network.nodes or destination not in network.nodes:
        return False
    return network.has_path_between(origin, destination)


def airlift_possible(
    game: Game, origin: ControlPoint, destination: ControlPoint
) -> bool:
    """True if some squadron of origin's side, with aircraft, could airlift it.

    Uses AirliftPlanner.compatible_with_mission (TRANSPORT-capable, both bases
    usable, helicopter leg range) so the answer matches what the airlift
    planner will accept. Ignores whether the aircraft are free this turn:
    busy squadrons free up at the next turn start, when waiting transfers are
    planned again.
    """
    from game.ato.flighttype import FlightType
    from game.transfers import AirliftPlanner

    planner = AirliftPlanner.__new__(AirliftPlanner)
    planner.transfer = SimpleNamespace(  # type: ignore[assignment]
        origin=origin, position=origin
    )
    planner.next_stop = destination
    for squadron in game.air_wing_for(origin.captured).iter_squadrons():
        if (
            squadron.owned_aircraft > 0
            and squadron.aircraft.capable_of(FlightType.TRANSPORT)
            and planner.compatible_with_mission(squadron.aircraft, squadron.location)
        ):
            return True
    return False


@dataclass(eq=False)
class _Base:
    """One REDFOR base's ground units against its target this turn."""

    cp: ControlPoint
    frontline: bool
    target: int
    present: int
    incoming: int

    @property
    def shortfall(self) -> int:
        """Units still needed after everything already on its way arrives."""
        return max(0, self.target - self.present - self.incoming)

    @property
    def spare(self) -> int:
        """Units this base can give away and stay at its own target."""
        return max(0, self.present - self.target)


class RedforSupplyPlanner:
    """Refills REDFOR bases that are below their ground-unit target.

    Each turn:
      1. Every REDFOR base gets a target: frontline bases (next to an active
         front) the frontline target, the rest the rear target (Settings).
         Units already on their way to a base count towards it.
      2. Bases below target want units; bases above it have spare units.
      3. Pairs are tried frontline bases first, then nearest first. So a base
         with spare units feeds the closest base that needs them, and a full
         base is skipped for the next one out.
      4. Each order moves up to CONVOY_SIZE units, by road convoy or airlift
         depending on distance (see the module docstring).
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        self.red = game.red

    def plan(self) -> None:
        if not self._is_enabled():
            return

        from game.logistics.transport_tiers import (
            Tier,
            preferred_airlift,
            road_path,
            tier_for,
        )
        from game.transfers import TransferOrder

        bases = self._bases()
        needy = [b for b in bases if b.shortfall > 0]
        donors = [b for b in bases if b.spare > 0]
        if not needy or not donors:
            return

        max_dist_m = self._setting("redfor_resupply_max_distance_km", 400) * 1000.0
        pairs: list[tuple[_Base, _Base, float]] = []
        for dest in needy:
            for source in donors:
                if source is dest:
                    continue
                dist_m = _distance(source.cp, dest.cp)
                if dist_m <= max_dist_m:
                    pairs.append((source, dest, dist_m))
        # Frontline bases first, then shortest trip first.
        pairs.sort(key=lambda p: (not p[1].frontline, p[2]))

        now = datetime.utcnow()
        network = self.red.transit_network
        max_transfers = self._setting("redfor_resupply_max_bases", MAX_CONVOYS_PER_TURN)
        created = 0

        for source, dest, dist_m in pairs:
            if created >= max_transfers:
                break
            count = min(CONVOY_SIZE, source.spare, dest.shortfall)
            if count <= 0:
                continue  # topped up or emptied by an earlier order this turn
            if self._pending_between(source.cp, dest.cp):
                continue
            if not has_transfer_route(self.game, source.cp, dest.cp):
                continue

            tier = tier_for(dist_m)
            by_road = (
                tier is Tier.SHORT
                and road_path(network, source.cp, dest.cp) is not None
            )
            preferred = None if by_road else preferred_airlift(tier)
            # Every new transfer strips its units from the source base at once,
            # so don't order an airlift no Red aircraft can fly: those units
            # would sit in limbo indefinitely.
            if not by_road and not airlift_possible(self.game, source.cp, dest.cp):
                logger.debug(
                    "RedforSupplyPlanner: no Red transport can fly %s -> %s",
                    source.cp.name,
                    dest.cp.name,
                )
                continue

            units = _select_units(source.cp, count)
            if not units:
                continue
            sent = sum(units.values())
            mode = "convoy" if by_road else f"airlift ({preferred} preferred)"
            try:
                transfer = TransferOrder(source.cp, dest.cp, units)
                if not by_road:
                    transfer.request_airflift = True
                    transfer.preferred_airlift = preferred
                self.red.transfers.new_transfer(transfer, now)
            except Exception as e:
                logger.warning(
                    "RedforSupplyPlanner: failed to create %s %s->%s: %s",
                    mode,
                    source.cp.name,
                    dest.cp.name,
                    e,
                )
                continue

            source.present -= sent
            dest.incoming += sent
            created += 1
            logger.info(
                "RedforSupplyPlanner: %s %s -> %s (%.0f km, %d units, %s short %d)",
                mode,
                source.cp.name,
                dest.cp.name,
                dist_m / 1000.0,
                sent,
                dest.cp.name,
                dest.shortfall,
            )

        if created:
            logger.info(
                "RedforSupplyPlanner: created %d transfer(s) this turn.", created
            )

    def _bases(self) -> list[_Base]:
        frontline_target = self._setting("redfor_resupply_frontline_target", 20)
        rear_target = self._setting("redfor_resupply_rear_target", 6)
        incoming: dict[int, int] = {}
        for transfer in self.red.transfers:
            dest = getattr(transfer, "destination", None)
            if dest is not None:
                incoming[id(dest)] = incoming.get(id(dest), 0) + _size(transfer)

        bases = []
        for cp in self.game.theater.controlpoints:
            if not cp.captured.is_red or not cp.can_deploy_ground_units:
                continue
            frontline = bool(getattr(cp, "has_active_frontline", False))
            bases.append(
                _Base(
                    cp=cp,
                    frontline=frontline,
                    target=frontline_target if frontline else rear_target,
                    present=_armor_count(cp),
                    incoming=incoming.get(id(cp), 0),
                )
            )
        return bases

    def _pending_between(self, source: ControlPoint, destination: ControlPoint) -> bool:
        return any(
            t.origin is source and t.destination is destination
            for t in self.red.transfers
        )

    def _is_enabled(self) -> bool:
        return bool(self._setting("redfor_resupply_enabled", True))

    def _setting(self, name: str, default: Any) -> Any:
        settings = getattr(self.game, "settings", None)
        if settings is None:
            return default
        return getattr(settings, name, default)


def _distance(a: ControlPoint, b: ControlPoint) -> float:
    try:
        return a.position.distance_to_point(b.position)
    except Exception:
        return 0.0


def _armor_count(cp: ControlPoint) -> int:
    try:
        return sum(n for n in cp.base.armor.values() if n > 0)
    except AttributeError:
        return 0


def _size(transfer: Any) -> int:
    try:
        return sum(transfer.units.values())
    except AttributeError:
        return 0


def _select_units(cp: ControlPoint, count: int) -> dict[GroundUnitType, int]:
    """Up to count units, taken one at a time from the most plentiful type.

    Gives a mixed convoy and never empties a scarce type first.
    """
    pool = {t: n for t, n in cp.base.armor.items() if n > 0}
    units: dict[GroundUnitType, int] = {}
    while count > 0 and pool:
        unit_type = max(pool, key=lambda t: pool[t])
        units[unit_type] = units.get(unit_type, 0) + 1
        pool[unit_type] -= 1
        if pool[unit_type] == 0:
            del pool[unit_type]
        count -= 1
    return units
