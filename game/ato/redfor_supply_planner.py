"""
game/ato/redfor_supply_planner.py

Automatically creates ground convoy OR airlift transfer orders between
REDFOR bases each turn, based on distance:
  - Under 150 km  -> land convoy (visible on map, targetable by player)
  - Over 150 km   -> airlift (requires transport aircraft at source base)
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.game import Game

logger = logging.getLogger(__name__)

CONVOY_SIZE = 4
MAX_CONVOYS_PER_TURN = 3
AIRLIFT_DISTANCE_THRESHOLD_KM = 150.0


class RedforSupplyPlanner:
    """Plans automatic ground supply transfers between REDFOR control points.

    Short routes (< 150 km) use land convoys.
    Long routes (>= 150 km) use airlift if transport aircraft are available.
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        self.red = game.red

    def plan(self) -> None:
        if not self._is_enabled():
            return

        from game.transfers import TransferOrder
        from game.theater.transitnetwork import TransitConnection

        now = datetime.utcnow()
        transfers_created = 0
        max_transfers = self._max_convoys()
        threshold_m = AIRLIFT_DISTANCE_THRESHOLD_KM * 1000.0

        settings = getattr(self.game, "settings", None)
        max_dist_km = getattr(settings, "redfor_resupply_max_distance_km", 200)
        max_dist_m = max_dist_km * 1000.0

        red_cps = [
            cp for cp in self.game.theater.controlpoints
            if not cp.captured and cp.can_deploy_ground_units
        ]

        if len(red_cps) < 2:
            return

        # Collect candidate pairs — both road-connected and airlift-capable
        candidate_pairs = []
        transit_network = self.red.transit_network

        for cp in red_cps:
            if cp not in transit_network.nodes:
                continue
            for neighbor, link_type in transit_network.nodes[cp].items():
                if neighbor.captured or not neighbor.can_deploy_ground_units:
                    continue

                try:
                    dist_m = cp.position.distance_to_point(neighbor.position)
                except Exception:
                    dist_m = 0.0

                if dist_m > max_dist_m:
                    continue

                use_airlift = dist_m >= threshold_m

                # Road pairs: only if road link exists
                if not use_airlift and link_type != TransitConnection.Road:
                    continue

                pair = tuple(sorted([cp.id, neighbor.id]))
                existing = [tuple(sorted([p[0].id, p[1].id])) for p in candidate_pairs]
                if pair not in existing:
                    candidate_pairs.append((cp, neighbor, dist_m, use_airlift))

        if not candidate_pairs:
            logger.debug("RedforSupplyPlanner: no eligible REDFOR base pairs found.")
            return

        # Sort: short road routes first (more reliable), then airlift
        candidate_pairs.sort(key=lambda t: (t[3], t[2]))
        random.shuffle(candidate_pairs[:max(1, len(candidate_pairs) // 2)])

        for source, destination, dist_m, use_airlift in candidate_pairs:
            if transfers_created >= max_transfers:
                break

            units = self._select_units(source, CONVOY_SIZE)
            if not units:
                continue

            mode = "airlift" if use_airlift else "convoy"
            dist_km = dist_m / 1000.0

            try:
                transfer = TransferOrder(source, destination, units)
                if use_airlift:
                    transfer.request_airflift = True
                self.red.transfers.new_transfer(transfer, now)
                transfers_created += 1
                logger.info(
                    "RedforSupplyPlanner: %s %s -> %s (%.0f km, %d units)",
                    mode, source.name, destination.name, dist_km, len(units),
                )
            except Exception as e:
                logger.warning(
                    "RedforSupplyPlanner: failed to create %s %s->%s: %s",
                    mode, source.name, destination.name, e,
                )

        if transfers_created:
            logger.info(
                "RedforSupplyPlanner: created %d transfer(s) this turn.", transfers_created
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

    def _select_units(self, cp, count: int) -> dict:
        units = {}
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
