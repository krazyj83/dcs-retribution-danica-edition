"""Automatic advanced IADS: place the buildings Skynet needs.

Retribution's advanced IADS links SAM sites and EWRs to comms towers, power
plants and command centers. Those buildings normally only exist where the
campaign author placed them in the .miz; without them the network falls back to
basic mode. With the "Build advanced IADS automatically" setting, the game
places them itself when a new campaign is generated:

- a comms tower for every cluster of SAM/EWR sites of a base (sites within
  CLUSTER_RADIUS of each other), so every site is within comms range (15 nm);
- a power plant for every group of sites within POWER_CLUSTER_RADIUS, so every
  site is within power range (35 nm);
- one command center per coalition, at its base furthest from the enemy.

A building is put on land, away from the base's runway and other ground
objects; when no such spot is found it is skipped. Afterwards the normal
range-based builder (IadsNetwork.initialize_network_from_range) connects
everything.

Bases whose campaign already places IADS buildings, and campaigns with an
iads_config, are left as the author made them.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence, TypeVar

from dcs.mapping import Point

if TYPE_CHECKING:
    from game.theater.controlpoint import ControlPoint

#: Sites within this distance of the first site of a cluster share a comms
#: tower. The tower goes near the cluster's centre, so every site is at most
#: twice this from it: 24 km, inside the 27.8 km (15 nm) comms range.
CLUSTER_RADIUS_M = 12_000.0
#: Same for power plants: at most 60 km from the plant, inside 64.8 km (35 nm).
POWER_CLUSTER_RADIUS_M = 30_000.0

#: Keep new buildings this far from the base (runway, parking) ...
MIN_DISTANCE_FROM_BASE_M = 2_000.0
#: ... and from any other ground object.
MIN_DISTANCE_FROM_OBJECTS_M = 500.0
#: How far from the wanted spot a building may be moved to find land.
MAX_SEARCH_RADIUS_M = 8_000.0
SEARCH_STEP_M = 1_000.0
SEARCH_BEARINGS = 12

T = TypeVar("T")


def cluster(
    items: Sequence[T], position: Callable[[T], Point], radius_m: float
) -> list[list[T]]:
    """Greedy clusters: the first unassigned item and everything within radius_m.

    Items are taken in the order given, so callers put the most important
    first (e.g. sorted by distance from the base).
    """
    left = list(items)
    clusters: list[list[T]] = []
    while left:
        seed = left.pop(0)
        members = [seed]
        for item in list(left):
            if position(seed).distance_to_point(position(item)) <= radius_m:
                members.append(item)
                left.remove(item)
        clusters.append(members)
    return clusters


def centroid(points: Iterable[Point]) -> Point:
    pts = list(points)
    x = sum(p.x for p in pts) / len(pts)
    y = sum(p.y for p in pts) / len(pts)
    return Point(x, y, pts[0]._terrain)


def find_spot(
    wanted: Point,
    base: Point,
    avoid: Sequence[Point],
    on_land: Callable[[Point], bool],
    reach: Sequence[Point] = (),
    reach_m: float = math.inf,
) -> Optional[Point]:
    """The spot nearest ``wanted`` that is on land, clear of the base and of
    ``avoid``, and within ``reach_m`` of every point in ``reach``.

    Searches rings of SEARCH_STEP_M around ``wanted`` out to
    MAX_SEARCH_RADIUS_M. Returns None when nothing fits.
    """
    steps = int(MAX_SEARCH_RADIUS_M // SEARCH_STEP_M)
    for ring in range(0, steps + 1):
        distance = ring * SEARCH_STEP_M
        bearings = (
            [0.0]
            if ring == 0
            else [i * 360.0 / SEARCH_BEARINGS for i in range(SEARCH_BEARINGS)]
        )
        for bearing in bearings:
            spot = wanted.point_from_heading(bearing, distance) if distance else wanted
            if spot.distance_to_point(base) < MIN_DISTANCE_FROM_BASE_M:
                continue
            if any(
                spot.distance_to_point(p) < MIN_DISTANCE_FROM_OBJECTS_M for p in avoid
            ):
                continue
            if any(spot.distance_to_point(p) > reach_m for p in reach):
                continue
            if not on_land(spot):
                continue
            return spot
    return None


def enemy_distance(cp: ControlPoint, control_points: Iterable[ControlPoint]) -> float:
    """Distance from cp to the nearest control point of the other side."""
    distances = [
        cp.position.distance_to_point(other.position)
        for other in control_points
        if other is not cp
        and not other.captured.is_neutral
        and other.captured != cp.captured
    ]
    return min(distances, default=0.0)
