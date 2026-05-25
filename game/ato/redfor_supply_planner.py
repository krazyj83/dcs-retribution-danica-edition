"""
game/ato/redfor_supply_planner.py

Automatically creates ground convoy transfer orders between REDFOR bases
each turn, mirroring the blue player's manual transfer system.

Wire into game turn processing by calling:
    RedforSupplyPlanner(game).plan()
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.game import Game

logger = logging.getLogger(__name__)

# How many ground units to send per convoy
CONVOY_SIZE = 4

# Maximum number of convoys to create per turn
MAX_CONVOYS_PER_TURN = 3


class RedforSupplyPlanner:
    """Plans automatic ground supply convoys between REDFOR control points.

    Each turn, finds REDFOR bases connected by road via the transit network
    and creates TransferOrder objects to move ground units between them.
    This causes ConvoyGenerator to spawn vehicle groups in the DCS mission,
    making REDFOR supply lines visible and targetable by the player.
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        self.red = game.red

    def plan(self) -> None:
        """Create convoy transfer orders for this turn."""
        if not self._is_enabled():
            return

        from game.transfers import TransferOrder
        from game.theater.transitnetwork import TransitConnection

        now = datetime.utcnow()
        convoys_created = 0
        max_convoys = self._max_convoys()

        # Get all red control points that have ground units
        red_cps = [
            cp for cp in self.game.theater.controlpoints
            if not cp.captured and cp.can_deploy_ground_units
        ]

        if len(red_cps) < 2:
            return

        # Build list of connected pairs via road
        connected_pairs = []
        transit_network = self.red.transit_network
        for cp in red_cps:
            if cp not in transit_network.nodes:
                continue
            for neighbor, link_type in transit_network.nodes[cp].items():
                if (
                    link_type == TransitConnection.Road
                    and not neighbor.captured
                    and neighbor.can_deploy_ground_units
                ):
                    # Avoid duplicates (A->B and B->A)
                    pair = tuple(sorted([cp.id, neighbor.id]))
                    if pair not in [tuple(sorted([p[0].id, p[1].id])) for p in connected_pairs]:
                        connected_pairs.append((cp, neighbor))

        if not connected_pairs:
            logger.debug("RedforSupplyPlanner: no road-connected REDFOR base pairs found.")
            return

        # Shuffle for variety each turn
        random.shuffle(connected_pairs)

        for source, destination in connected_pairs:
            if convoys_created >= max_convoys:
                break

            # Find units available at source
            units = self._select_units(source, CONVOY_SIZE)
            if not units:
                continue

            try:
                transfer = TransferOrder(source, destination, units)
                self.red.transfers.new_transfer(transfer, now)
                convoys_created += 1
                logger.info(
                    "RedforSupplyPlanner: convoy %s -> %s (%d units)",
                    source.name, destination.name, len(units),
                )
            except Exception as e:
                logger.warning("RedforSupplyPlanner: failed to create convoy: %s", e)

        if convoys_created:
            logger.info("RedforSupplyPlanner: created %d convoy(s) this turn.", convoys_created)

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
        """Select ground units from a control point to send in a convoy.

        Returns a dict of {GroundUnitType: quantity} or empty dict if none available.
        """
        units = {}
        try:
            if not hasattr(cp, "base") or not hasattr(cp.base, "armor"):
                return {}
            for unit_type, available in cp.base.armor.items():
                if available <= 0:
                    continue
                # Send at most half the available units, up to count
                send = min(available // 2, count - sum(units.values()))
                if send > 0:
                    units[unit_type] = send
                if sum(units.values()) >= count:
                    break
        except Exception as e:
            logger.debug("RedforSupplyPlanner: error selecting units from %s: %s", cp.name, e)
        return units
