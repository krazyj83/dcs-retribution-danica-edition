"""Which kind of transport REDFOR uses to move supplies, by distance.

REDFOR only — BLUEFOR supplies are flown by players (see transfer_flights).

    SHORT   under 120 km        road convoy, if the bases are road-connected
    MEDIUM  120 km to 220 km    airlift, helicopters preferred
    LONG    over 220 km         airlift, planes preferred

SHORT without a road link is airlifted like MEDIUM. The airlift preference is
passed to Retribution's AirliftPlanner via TransferOrder.preferred_airlift; it
falls back to the other kind when no preferred aircraft is available.
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import TYPE_CHECKING, Optional

from game.theater.transitnetwork import TransitConnection

if TYPE_CHECKING:
    from game.theater import ControlPoint
    from game.theater.transitnetwork import TransitNetwork

SHORT_MAX_KM = 120.0
MEDIUM_MAX_KM = 220.0


class Tier(Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


def tier_for(distance_m: float) -> Tier:
    km = distance_m / 1000
    if km < SHORT_MAX_KM:
        return Tier.SHORT
    if km <= MEDIUM_MAX_KM:
        return Tier.MEDIUM
    return Tier.LONG


def preferred_airlift(tier: Tier) -> str:
    """The value for TransferOrder.preferred_airlift: helicopter or plane."""
    return "plane" if tier is Tier.LONG else "helicopter"


def road_path(
    network: TransitNetwork, origin: ControlPoint, destination: ControlPoint
) -> Optional[list[ControlPoint]]:
    """Control points from origin to destination using road links only.

    Includes both ends. None if the bases are not road-connected.
    """
    if origin not in network.nodes or destination not in network.nodes:
        return None
    previous: dict[ControlPoint, Optional[ControlPoint]] = {origin: None}
    queue = deque([origin])
    while queue:
        current = queue.popleft()
        if current is destination:
            path = [current]
            while (step := previous[path[-1]]) is not None:
                path.append(step)
            return list(reversed(path))
        for neighbour, link in network.nodes[current].items():
            if link is TransitConnection.Road and neighbour not in previous:
                previous[neighbour] = current
                queue.append(neighbour)
    return None
