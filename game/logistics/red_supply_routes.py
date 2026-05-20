"""
game/logistics/red_supply_routes.py

Automatically generates convoy supply routes between red-faction control points.
Called at the end of MizCampaignLoader.add_supply_routes() — no .miz editing needed.

Each red CP is connected to its nearest red neighbours (up to MAX_NEIGHBOURS)
within MAX_DISTANCE_KM. Routes are straight-line; spawn points are interpolated
at 100ft intervals from the CP position toward the destination.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from game.theater.conflicttheater import ConflictTheater
    from dcs.mapping import Point

logger = logging.getLogger(__name__)

# ── Tuneable constants ────────────────────────────────────────────────────────
MAX_NEIGHBOURS: int = 3        # Max red neighbours each CP connects to
MAX_DISTANCE_KM: float = 250   # Only connect CPs within this range (km)
SPAWN_DEPTH_M: float = 500     # How far from the CP to generate spawn points
# ─────────────────────────────────────────────────────────────────────────────


def _make_spawn_points(start: "Point", end: "Point") -> Tuple["Point", ...]:
    """
    Generate interpolated spawn points at ~30m intervals from start toward end,
    covering SPAWN_DEPTH_M metres. This mimics what _construct_cp_spawnpoints
    does for blue routes but without needing a CP_CONVOY_SPAWN marker in the miz.
    """
    total = start.distance_to_point(end)
    if total < 1:
        return (start,)

    step = 30.0  # metres between spawn points (~100ft)
    depth = min(SPAWN_DEPTH_M, total * 0.4)  # don't overshoot midpoint
    points: list["Point"] = [start]
    dist = step
    while dist <= depth:
        fraction = dist / total
        points.append(start.lerp(end, fraction))
        dist += step

    return tuple(points)


def auto_generate_red_supply_routes(theater: "ConflictTheater") -> None:
    """
    Connect every red control point to its nearest red neighbours with
    straight-line convoy routes. Call this at the end of add_supply_routes()
    so it runs after any manual blue routes have already been registered.
    """
    # Collect all red CPs
    red_cps = [cp for cp in theater.controlpoints if cp.captured.is_red]

    if not red_cps:
        logger.debug("No red control points found; skipping auto supply routes.")
        return

    max_dist_m = MAX_DISTANCE_KM * 1000
    routes_created = 0

    for cp in red_cps:
        # Sort all other red CPs by distance from this one
        candidates = sorted(
            (other for other in red_cps if other is not cp),
            key=lambda other: cp.position.distance_to_point(other.position),
        )

        neighbours_added = 0
        for neighbour in candidates:
            if neighbours_added >= MAX_NEIGHBOURS:
                break

            dist = cp.position.distance_to_point(neighbour.position)
            if dist > max_dist_m:
                break  # sorted, so all remaining are farther

            # Skip if a route already exists in either direction
            if neighbour in cp.convoy_routes or cp in neighbour.convoy_routes:
                continue

            waypoints = [cp.position, neighbour.position]
            rev_waypoints = [neighbour.position, cp.position]

            o_spawns = _make_spawn_points(cp.position, neighbour.position)
            d_spawns = _make_spawn_points(neighbour.position, cp.position)

            try:
                cp.create_convoy_route(neighbour, waypoints, o_spawns)
                neighbour.create_convoy_route(cp, rev_waypoints, d_spawns)
            except Exception:
                logger.exception(
                    "Failed to create red convoy route %s <-> %s",
                    cp.name,
                    neighbour.name,
                )
                continue

            logger.debug(
                "Red auto-route: %s <-> %s (%.0f km)",
                cp.name,
                neighbour.name,
                dist / 1000,
            )
            neighbours_added += 1
            routes_created += 1

    logger.info(
        "Auto-generated %d red supply route(s) across %d red control point(s).",
        routes_created,
        len(red_cps),
    )
