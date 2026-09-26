"""
game/ato/redfor_supply_planner.py

Automatically creates ground convoy OR airlift transfer orders between
REDFOR bases each turn, using the shared distance bands in
game/logistics/transport_tiers.py:
  - Under 120 km, road-connected -> land convoy (visible, targetable)
  - Under 220 km                 -> airlift, helicopters preferred
  - Over 220 km                  -> airlift, planes preferred
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Optional

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


class RedforSupplyPlanner:
    """Plans automatic ground supply transfers between REDFOR control points.

    See the module docstring for which transport each distance uses.
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

        now = datetime.utcnow()
        transfers_created = 0
        max_transfers = self._max_convoys()

        settings = getattr(self.game, "settings", None)
        max_dist_km = getattr(settings, "redfor_resupply_max_distance_km", 400)
        max_dist_m = max_dist_km * 1000.0

        red_cps = [
            cp
            for cp in self.game.theater.controlpoints
            if cp.captured.is_red and cp.can_deploy_ground_units
        ]

        if len(red_cps) < 2:
            return

        # Candidate pairs: (source, destination, distance, by_road, preferred airlift)
        candidate_pairs: list[
            tuple[ControlPoint, ControlPoint, float, bool, Optional[str]]
        ] = []
        transit_network = self.red.transit_network

        for cp in red_cps:
            if cp not in transit_network.nodes:
                continue
            for neighbor in list(transit_network.nodes[cp]):
                if not neighbor.captured.is_red or not neighbor.can_deploy_ground_units:
                    continue

                try:
                    dist_m = cp.position.distance_to_point(neighbor.position)
                except Exception:
                    dist_m = 0.0

                if dist_m > max_dist_m:
                    continue

                tier = tier_for(dist_m)
                by_road = (
                    tier is Tier.SHORT
                    and road_path(transit_network, cp, neighbor) is not None
                )
                preferred = None if by_road else preferred_airlift(tier)

                pair = tuple(sorted([cp.id, neighbor.id]))
                existing = [tuple(sorted([p[0].id, p[1].id])) for p in candidate_pairs]
                if pair not in existing:
                    candidate_pairs.append((cp, neighbor, dist_m, by_road, preferred))

        if not candidate_pairs:
            logger.debug("RedforSupplyPlanner: no eligible REDFOR base pairs found.")
            return

        # Road routes first (more reliable), then airlift; nearest first within
        # each. Shuffle the front half in place so the same pair doesn't win
        # every turn (slicing and shuffling the copy had no effect).
        candidate_pairs.sort(key=lambda t: (not t[3], t[2]))
        half = max(1, len(candidate_pairs) // 2)
        front = candidate_pairs[:half]
        random.shuffle(front)
        candidate_pairs[:half] = front

        for source, destination, dist_m, by_road, preferred in candidate_pairs:
            if transfers_created >= max_transfers:
                break

            units = self._select_units(source, CONVOY_SIZE)
            if not units:
                continue

            mode = "convoy" if by_road else f"airlift ({preferred} preferred)"
            dist_km = dist_m / 1000.0

            if not has_transfer_route(self.game, source, destination):
                continue
            # Every new transfer strips its units from the source base at once
            # (new_transfer -> commit_losses). Don't stack a second order on a
            # pair that is still waiting, and don't order an airlift no Red
            # aircraft can fly: those units would sit in limbo indefinitely.
            if self._pending_between(source, destination):
                continue
            if not by_road and not airlift_possible(self.game, source, destination):
                logger.debug(
                    "RedforSupplyPlanner: no Red transport can fly %s -> %s",
                    source.name,
                    destination.name,
                )
                continue

            try:
                transfer = TransferOrder(source, destination, units)
                if not by_road:
                    transfer.request_airflift = True
                    transfer.preferred_airlift = preferred
                self.red.transfers.new_transfer(transfer, now)
                transfers_created += 1
                logger.info(
                    "RedforSupplyPlanner: %s %s -> %s (%.0f km, %d units)",
                    mode,
                    source.name,
                    destination.name,
                    dist_km,
                    len(units),
                )
            except Exception as e:
                logger.warning(
                    "RedforSupplyPlanner: failed to create %s %s->%s: %s",
                    mode,
                    source.name,
                    destination.name,
                    e,
                )

        if transfers_created:
            logger.info(
                "RedforSupplyPlanner: created %d transfer(s) this turn.",
                transfers_created,
            )

    def _pending_between(self, source: ControlPoint, destination: ControlPoint) -> bool:
        return any(
            t.origin is source and t.destination is destination
            for t in self.red.transfers
        )

    def _is_enabled(self) -> bool:
        settings = getattr(self.game, "settings", None)
        if settings is None:
            return True
        return getattr(settings, "redfor_resupply_enabled", True)

    def _max_convoys(self) -> int:
        settings = getattr(self.game, "settings", None)
        if settings is None:
            return MAX_CONVOYS_PER_TURN
        return getattr(settings, "redfor_resupply_max_bases", MAX_CONVOYS_PER_TURN)

    def _select_units(self, cp: ControlPoint, count: int) -> dict[GroundUnitType, int]:
        units: dict[GroundUnitType, int] = {}
        try:
            if not hasattr(cp, "base") or not hasattr(cp.base, "armor"):
                return {}
            for unit_type, available in cp.base.armor.items():
                if available <= 0:
                    continue
                send = min(available // 2, count - sum(units.values()))
                if send > 0:
                    units[unit_type] = send
                if sum(units.values()) >= count:
                    break
        except Exception as e:
            logger.debug(
                "RedforSupplyPlanner: error selecting units from %s: %s", cp.name, e
            )
        return units
