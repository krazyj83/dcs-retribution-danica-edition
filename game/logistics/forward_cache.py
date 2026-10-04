"""Forward caches: cargo crates left in a drop zone stay there.

A weapon crate set down inside a friendly drop zone (outside the base itself)
no longer goes straight into the base's stores. It stays on the ground as a
crate of the drop zone's forward cache, and is placed again, where it lay, in
every following mission. From there pilots can sling or load it again:

    where a cache crate is at mission end       what happens
    ------------------------------------------  ----------------------------------
    on the ground at a friendly base            into that base's stores (what
                                                doesn't fit stays in the cache)
    on the ground anywhere else                 stays where it is (still cached)
    destroyed                                   lost
    gone or still in the air (inside or under   back where it was at the start
    an aircraft at the end)                     of the mission

"At a base" means within the base's radius (crate_delivery.base_radius_m). A
drop zone close enough to be inside that radius just delivers to the base.

The crates are ordinary cargo crates of the mission script
(resources/plugins/base/retribution_cargo.lua) with a transfer id starting
with "C", so they are reported like any other crate.

Removing a drop zone returns its cache to the base the zone belongs to (lost
if that base is no longer friendly).

The caches are stored on the LogisticsManager (``_drop_zone_caches``); old
saves start with none.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from game.logistics.cargo import manifest_summary, manifest_weight_kg
from game.theater.player import Player

if TYPE_CHECKING:
    from game import Game
    from game.logistics import DropZone, LogisticsManager
    from game.logistics.crate_delivery import CrateReport
    from game.theater import ControlPoint

logger = logging.getLogger(__name__)

#: Transfer ids of cache crates in the mission script start with this
#: (transfer ids are lower-case hex, so they never do).
CACHE_TID_PREFIX = "C"


@dataclass
class CacheCrate:
    #: The drop zone the crate was left in.
    dz_id: str
    contents: Dict[str, int]
    #: DCS map position (x north, z east).
    x: float
    z: float

    @property
    def label(self) -> str:
        return manifest_summary(self.contents)

    @property
    def mass_kg(self) -> float:
        return manifest_weight_kg(self.contents)


def enabled(game: Any) -> bool:
    settings = getattr(game, "settings", None)
    return bool(getattr(settings, "drop_zone_caches", False))


def caches(logistics: LogisticsManager) -> List[CacheCrate]:
    if not hasattr(logistics, "_drop_zone_caches"):
        logistics._drop_zone_caches = []
    crates: List[CacheCrate] = logistics._drop_zone_caches
    return crates


def cache_of(logistics: LogisticsManager, dz_id: str) -> Dict[str, int]:
    """What a drop zone's cache holds, all crates together."""
    total: Dict[str, int] = {}
    for crate in caches(logistics):
        if crate.dz_id == dz_id:
            for clsid, n in crate.contents.items():
                total[clsid] = total.get(clsid, 0) + n
    return total


def cache_tid(dz_id: str) -> str:
    return f"{CACHE_TID_PREFIX}{dz_id.replace('-', '')[:7]}"


def is_cache_tid(tid: str) -> bool:
    return tid.startswith(CACHE_TID_PREFIX)


def drop_zone_at(game: Game, x: float, z: float) -> Optional[DropZone]:
    """The active drop zone of a friendly base the point is in, if any."""
    from dcs.mapping import LatLng, Point

    point = Point(x, z, game.theater.terrain)
    for dz in game.logistics._drop_zones.values():
        if not dz.active or dz.cp_id is None:
            continue
        try:
            base = game.theater.find_control_point_by_id(dz.cp_id)
        except KeyError:
            continue
        if base is None or base.captured is not Player.BLUE:
            continue
        try:
            centre = Point.from_latlng(LatLng(dz.lat, dz.lon), game.theater.terrain)
        except Exception:
            continue
        if centre.distance_to_point(point) <= dz.radius_m:
            return dz
    return None


def base_at(game: Game, x: float, z: float) -> Optional[ControlPoint]:
    """The friendly base the point is within the radius of (drop zones aside)."""
    from dcs.mapping import Point

    from game.logistics.crate_delivery import base_radius_m, friendly_bases

    point = Point(x, z, game.theater.terrain)
    best = None
    for cp in friendly_bases(game):
        distance = cp.position.distance_to_point(point)
        if distance <= base_radius_m(cp) and (best is None or distance < best[0]):
            best = (distance, cp)
    return best[1] if best else None


def leave_in_cache(
    logistics: LogisticsManager, dz: DropZone, report: CrateReport
) -> None:
    """A transfer crate set down in a drop zone becomes a cache crate."""
    caches(logistics).append(
        CacheCrate(dz.dz_id, dict(report.contents), report.x, report.z)
    )


def _by_tid(game: Game) -> Dict[str, List[CacheCrate]]:
    out: Dict[str, List[CacheCrate]] = {}
    for crate in caches(game.logistics):
        out.setdefault(cache_tid(crate.dz_id), []).append(crate)
    return out


def settle(game: Game, state_crates: List[Any]) -> List[str]:
    """Move the cache crates to where the mission left them. Log lines."""
    from game.logistics.crate_delivery import ON_GROUND_MAX_AGL_M, CrateReport

    logistics = game.logistics
    placed = placed_crates(game)
    if not placed:
        return []
    reports: Dict[str, CrateReport] = {}
    for data in state_crates:
        try:
            parsed = CrateReport.from_state(data)
        except (TypeError, ValueError):
            continue
        if is_cache_tid(parsed.tid):
            reports[parsed.name] = parsed
    if not reports:
        return []  # the mission script didn't report: leave the caches alone

    log: List[str] = []
    kept: List[CacheCrate] = []
    for name, crate in placed.items():
        report = reports.get(name)
        if report is None or not report.exists or report.agl > ON_GROUND_MAX_AGL_M:
            if report is not None and report.destroyed:
                log.append(f"Forward cache: {crate.label} destroyed")
                continue
            kept.append(crate)  # back where it was
            continue
        if report.destroyed:
            log.append(f"Forward cache: {crate.label} destroyed")
            continue
        base = base_at(game, report.x, report.z)
        if base is not None:
            overflow = logistics._put_weapons(base, crate.contents)
            delivered = {
                c: n - overflow.get(c, 0)
                for c, n in crate.contents.items()
                if n - overflow.get(c, 0) > 0
            }
            if delivered:
                log.append(
                    f"Forward cache: {manifest_summary(delivered)} delivered to "
                    f"{base.name}"
                )
            if overflow:
                kept.append(CacheCrate(crate.dz_id, overflow, report.x, report.z))
            continue
        dz = drop_zone_at(game, report.x, report.z)
        dz_id = dz.dz_id if dz is not None else crate.dz_id
        if dz is not None and dz.dz_id != crate.dz_id:
            log.append(f"Forward cache: {crate.label} moved to {dz.name}")
        kept.append(CacheCrate(dz_id, crate.contents, report.x, report.z))
    unplaced = [c for c in caches(logistics) if c not in placed.values()]
    logistics._drop_zone_caches = unplaced + kept
    return log


def placed_crates(game: Game) -> Dict[str, CacheCrate]:
    """Mission crate name -> cache crate, as generate() names them."""
    out: Dict[str, CacheCrate] = {}
    for tid, crates in _by_tid(game).items():
        for i, crate in enumerate(crates, start=1):
            out[f"Cache {tid} {i}/{len(crates)}: {crate.label}"] = crate
    return out


def release(game: Game, dz: DropZone) -> List[str]:
    """A drop zone was removed: its cache goes back to the zone's base."""
    logistics = game.logistics
    mine = [c for c in caches(logistics) if c.dz_id == dz.dz_id]
    if not mine:
        return []
    logistics._drop_zone_caches = [c for c in caches(logistics) if c.dz_id != dz.dz_id]
    base = None
    if dz.cp_id is not None:
        try:
            base = game.theater.find_control_point_by_id(dz.cp_id)
        except KeyError:
            base = None
    total: Dict[str, int] = {}
    for crate in mine:
        for clsid, n in crate.contents.items():
            total[clsid] = total.get(clsid, 0) + n
    if base is None or base.captured is not Player.BLUE:
        return [f"Forward cache at {dz.name}: {manifest_summary(total)} lost"]
    logistics._return_weapons(base.id, total)
    return [
        f"Forward cache at {dz.name}: {manifest_summary(total)} back to {base.name}"
    ]


def mission_crates(game: Game) -> List[Dict[str, Any]]:
    """The cache crates to place: name, position, mass and script data."""
    if not enabled(game):
        return []
    out: List[Dict[str, Any]] = []
    for name, crate in placed_crates(game).items():
        dz = game.logistics.get_drop_zone(crate.dz_id)
        source = str(dz.cp_id) if dz is not None and dz.cp_id is not None else ""
        out.append(
            {
                "name": name,
                "x": crate.x,
                "z": crate.z,
                "mass": crate.mass_kg,
                "script": {
                    "name": name,
                    "tid": cache_tid(crate.dz_id),
                    "source": source,
                    "contents": [
                        {"clsid": c, "count": n} for c, n in crate.contents.items()
                    ],
                },
            }
        )
    return out
