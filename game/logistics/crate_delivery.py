"""Settle weapon transfers from where their crates ended up in the mission.

The mission script (resources/plugins/base/retribution_cargo.lua) reports every
cargo crate at the end of the mission: the crates placed for the flight's
planned load, and the crates pilots ordered through the F10 "Cargo" menu.

For each crate:

    set down at a friendly base   delivered to THAT base (can be any friendly
                                  base; back at the pickup base = returned)
    destroyed                     lost
    anywhere else, or gone        planned cargo: back to the pickup base
    (e.g. still in the aircraft)  ordered cargo: never left the pickup base
                                  ...unless the flight was shot down: lost

"At a base" means on the ground inside one of the base's active drop zones, or
within BASE_RADIUS_M of the base (FARP/FOB: SMALL_BASE_RADIUS_M).

Ordered crates only leave the pickup base's stock when they are delivered or
lost, so an order the pilot never picked up costs nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple
from uuid import UUID

from dcs.mapping import Point

from game.theater.player import Player

if TYPE_CHECKING:
    from game import Game
    from game.logistics import LogisticsManager, LogisticsTransfer
    from game.theater import ControlPoint

logger = logging.getLogger(__name__)

#: A crate this close to an airfield counts as at that airfield.
BASE_RADIUS_M = 2500.0
#: FARPs, FOBs and other small bases.
SMALL_BASE_RADIUS_M = 750.0
#: Higher than this above the ground: still hanging under a helicopter.
ON_GROUND_MAX_AGL_M = 3.0


def base_radius_m(cp: ControlPoint) -> float:
    return BASE_RADIUS_M if cp.dcs_airport is not None else SMALL_BASE_RADIUS_M


def friendly_bases(game: Game) -> List[ControlPoint]:
    """Bases a crate can be delivered to or ordered at (no ships)."""
    return [
        cp
        for cp in game.theater.controlpoints
        if cp.captured is Player.BLUE and not cp.is_fleet
    ]


def friendly_base_at(game: Game, x: float, z: float) -> Optional[ControlPoint]:
    """The friendly base a crate at DCS (x, z) is at, if any."""
    from dcs.mapping import LatLng

    point = Point(x, z, game.theater.terrain)
    best: Optional[Tuple[float, ControlPoint]] = None
    for cp in friendly_bases(game):
        distance = cp.position.distance_to_point(point)
        inside = distance <= base_radius_m(cp)
        if not inside:
            for dz in game.logistics.drop_zones_for_cp(cp.id):
                if not dz.active:
                    continue
                try:
                    centre = Point.from_latlng(
                        LatLng(dz.lat, dz.lon), game.theater.terrain
                    )
                except Exception:
                    continue
                if centre.distance_to_point(point) <= dz.radius_m:
                    inside = True
                    break
        if inside and (best is None or distance < best[0]):
            best = (distance, cp)
    return best[1] if best else None


@dataclass
class CrateReport:
    """One crate as reported by the mission script."""

    name: str
    tid: str
    source: str
    contents: Dict[str, int]
    requested: bool
    destroyed: bool
    exists: bool
    x: float = 0.0
    z: float = 0.0
    agl: float = 0.0

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> CrateReport:
        contents: Dict[str, int] = {}
        for entry in data.get("contents") or []:
            clsid = str(entry.get("clsid"))
            contents[clsid] = contents.get(clsid, 0) + int(entry.get("count", 0))
        return cls(
            name=str(data.get("name", "")),
            tid=str(data.get("tid", "")),
            source=str(data.get("source", "")),
            contents=contents,
            requested=bool(data.get("requested", False)),
            destroyed=bool(data.get("destroyed", False)),
            exists=bool(data.get("exists", False)),
            x=float(data.get("x") or 0.0),
            z=float(data.get("z") or 0.0),
            agl=float(data.get("agl") or 0.0),
        )


def reports_for(
    state_crates: List[Mapping[str, Any]], transfer_id: str
) -> List[CrateReport]:
    """Reports for one transfer. The script uses the first 8 characters."""
    short = transfer_id[:8]
    reports = []
    for data in state_crates:
        try:
            report = CrateReport.from_state(data)
        except (TypeError, ValueError):
            logger.warning("Unreadable cargo crate report: %r", data)
            continue
        if report.tid == short:
            reports.append(report)
    return reports


@dataclass
class Settlement:
    delivered: Dict[str, Dict[str, int]] = field(default_factory=dict)  # base name
    returned: Dict[str, int] = field(default_factory=dict)
    lost: Dict[str, int] = field(default_factory=dict)

    @property
    def delivered_count(self) -> int:
        return sum(sum(c.values()) for c in self.delivered.values())


def _add(into: Dict[str, int], contents: Mapping[str, int]) -> None:
    for clsid, n in contents.items():
        into[clsid] = into.get(clsid, 0) + n


def settle_transfer(
    game: Game,
    logistics: LogisticsManager,
    transfer: LogisticsTransfer,
    reports: List[CrateReport],
    flight_lost: bool,
) -> List[str]:
    """Apply crate reports to the stock. Returns log lines."""
    from game.logistics import TransferStatus
    from game.logistics.cargo import manifest_summary

    settlement = Settlement()
    for report in reports:
        source = _cp_by_id(game, report.source)
        # Base ids are UUIDs, despite the int annotations in LogisticsManager.
        source_id: Any = source.id if source is not None else transfer.source_cp_id
        at_base: Optional[ControlPoint] = None
        if report.exists and not report.destroyed and report.agl <= ON_GROUND_MAX_AGL_M:
            at_base = friendly_base_at(game, report.x, report.z)
        lost = report.destroyed or (not report.exists and flight_lost)

        if at_base is not None:
            if report.requested:
                logistics._take_weapons(source_id, report.contents)
            overflow = logistics._put_weapons(at_base, report.contents)
            if overflow:
                logistics._return_weapons(source_id, overflow)
            placed = {c: n - overflow.get(c, 0) for c, n in report.contents.items()}
            placed = {c: n for c, n in placed.items() if n > 0}
            if at_base.id == source_id:
                _add(settlement.returned, placed)
            elif placed:
                _add(settlement.delivered.setdefault(at_base.name, {}), placed)
            if overflow:
                _add(settlement.returned, overflow)
        elif lost:
            if report.requested:
                logistics._take_weapons(source_id, report.contents)
            _add(settlement.lost, report.contents)
        else:
            if not report.requested:
                logistics._return_weapons(source_id, report.contents)
            _add(settlement.returned, report.contents)

    tid = transfer.transfer_id[:8]
    lines = [
        f"Transfer {tid}: {manifest_summary(items)} delivered to {base}"
        for base, items in settlement.delivered.items()
    ]
    if settlement.returned:
        lines.append(
            f"Transfer {tid}: {manifest_summary(settlement.returned)} not delivered, "
            "back in stock"
        )
    if settlement.lost:
        lines.append(f"Transfer {tid}: {manifest_summary(settlement.lost)} lost")
    if not lines:
        lines.append(f"Transfer {tid}: nothing was carried")

    transfer.delivered = float(settlement.delivered_count)
    transfer.status = (
        TransferStatus.DELIVERED
        if settlement.delivered_count
        else TransferStatus.FAILED
    )
    return lines


def _cp_by_id(game: Game, cp_id: str) -> Optional[ControlPoint]:
    try:
        return game.theater.find_control_point_by_id(UUID(cp_id))
    except (KeyError, ValueError):
        return None
