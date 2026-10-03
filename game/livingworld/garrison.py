"""CTLD garrison: troops dropped with CTLD stay in the campaign.

Troops (and CTLD vehicles) that pilots unload with the CTLD menu used to vanish
when the mission ended. Now the ones still alive at the end are remembered and
placed again at the start of the next mission, unit by unit where they stood.
They stay CTLD groups, so pilots can pick them up and move them as usual.
Units killed in the mission are gone; a group with no unit left is dropped.

The loop:

    mission end   plugins/base/ctld_garrison.lua reports every CTLD-dropped
                  group still alive (ctld.droppedTroops/Vehicles BLUE and RED,
                  including the garrison groups it placed) into state.json
                  ("ctld_garrison": {groups = {...}}).
    debriefing    settle() replaces the stored garrison with that report. A
                  group standing inside an enemy-held base is lost (it can't
                  hold a base the other side owns). No report (CTLD plugin
                  off, or an old mission script): the garrison is kept as is.
    next mission  generate() adds the groups to the mission and writes
                  dcsRetributionGarrison = {groups = {{name, side, kind}}},
                  which the script uses to hand them back to CTLD.

The garrison is stored on the LogisticsManager (``_ctld_garrison``), which
keeps old saves loading (they start with an empty garrison).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

if TYPE_CHECKING:
    from game import Game

logger = logging.getLogger(__name__)

#: Group names of the garrison in the mission.
GROUP_PREFIX = "CTLD Garrison"
#: DCS coalition ids, as CTLD and the mission script report them.
RED, BLUE = 1, 2
KINDS = ("troops", "vehicles")


@dataclass
class GarrisonUnit:
    #: DCS type name ("Soldier M4").
    type: str
    x: float
    z: float
    #: Radians, DCS convention (0 = north).
    heading: float = 0.0


@dataclass
class GarrisonGroup:
    side: int
    #: "troops" (CTLD infantry) or "vehicles".
    kind: str
    units: List[GarrisonUnit] = field(default_factory=list)

    @property
    def centre(self) -> tuple[float, float]:
        n = len(self.units)
        return (
            sum(u.x for u in self.units) / n,
            sum(u.z for u in self.units) / n,
        )


def enabled(game: Any) -> bool:
    if not getattr(game.settings, "ctld_garrison", False):
        return False
    try:
        return bool(game.settings.plugin_option("ctld"))
    except (KeyError, AttributeError):
        return False


def stored(game: Any) -> List[GarrisonGroup]:
    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return []
    if not hasattr(logistics, "_ctld_garrison"):
        logistics._ctld_garrison = []
    return logistics._ctld_garrison


def _vehicle_types() -> Mapping[str, Any]:
    from dcs.vehicles import vehicle_map

    return vehicle_map


def parse_report(raw: Any) -> Optional[List[GarrisonGroup]]:
    """The groups in the mission script's report; None when there is none.

    Units of a type pydcs doesn't know (a mod that is no longer installed)
    are skipped, as are malformed entries.
    """
    if not isinstance(raw, Mapping) or "groups" not in raw:
        return None
    entries = raw.get("groups") or []
    if isinstance(entries, Mapping):  # an empty Lua table may arrive as {}
        entries = list(entries.values())
    known = _vehicle_types()
    groups: List[GarrisonGroup] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        try:
            side = int(entry.get("side", 0))
        except (TypeError, ValueError):
            continue
        if side not in (RED, BLUE):
            continue
        kind = str(entry.get("kind") or "troops")
        if kind not in KINDS:
            kind = "troops"
        units: List[GarrisonUnit] = []
        raw_units = entry.get("units") or []
        if isinstance(raw_units, Mapping):
            raw_units = list(raw_units.values())
        for unit in raw_units:
            if not isinstance(unit, Mapping):
                continue
            type_name = str(unit.get("type") or "")
            if type_name not in known:
                logger.warning("CTLD garrison: unknown unit type %r skipped", type_name)
                continue
            try:
                units.append(
                    GarrisonUnit(
                        type_name,
                        float(unit["x"]),
                        float(unit["z"]),
                        float(unit.get("heading") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if units:
            groups.append(GarrisonGroup(side, kind, units))
    return groups


def _enemy_base_at(game: Any, side: int, x: float, z: float) -> Optional[Any]:
    """The base of the other side the point is inside, if any."""
    from dcs.mapping import Point

    from game.logistics.crate_delivery import base_radius_m
    from game.theater.player import Player

    own = Player.BLUE if side == BLUE else Player.RED
    point = Point(x, z, game.theater.terrain)
    for cp in game.theater.controlpoints:
        if cp.is_fleet or cp.captured is own:
            continue
        if cp.position.distance_to_point(point) <= base_radius_m(cp):
            return cp
    return None


def _count(groups: List[GarrisonGroup], side: int) -> int:
    return sum(len(g.units) for g in groups if g.side == side)


def settle(game: Any, report: Any) -> List[str]:
    """Replace the stored garrison with the mission's report. Log lines."""
    if not getattr(game.settings, "ctld_garrison", False):
        return []
    groups = parse_report(report)
    if groups is None:
        return []
    kept: List[GarrisonGroup] = []
    log: List[str] = []
    for group in groups:
        cp = _enemy_base_at(game, group.side, *group.centre)
        if cp is not None:
            log.append(
                f"CTLD garrison: {len(group.units)} {group.kind} inside enemy-held "
                f"{cp.name} lost"
            )
            continue
        kept.append(group)
    before = stored(game)
    was, now = _count(before, BLUE), _count(kept, BLUE)
    game.logistics._ctld_garrison = kept
    if was or now:
        groups_blue = sum(1 for g in kept if g.side == BLUE)
        log.insert(
            0,
            f"CTLD garrison: {now} friendly troops and vehicles in {groups_blue} "
            f"group(s) stay in the field (was {was}).",
        )
    red = _count(kept, RED)
    if red:
        log.append(f"CTLD garrison: {red} enemy troops and vehicles stay in the field.")
    return log


def group_name(index: int) -> str:
    return f"{GROUP_PREFIX} {index}"


def generate(game: "Game", mission: Any) -> List[Dict[str, Any]]:
    """Add the stored garrison to the mission; the script's data rows."""
    from dcs.mapping import Point

    if not enabled(game):
        return []
    types = _vehicle_types()
    rows: List[Dict[str, Any]] = []
    for index, group in enumerate(stored(game), start=1):
        coalition = game.blue if group.side == BLUE else game.red
        country = mission.country(coalition.faction.country.name)
        if country is None:
            continue
        name = group_name(index)
        first, *rest = group.units
        vg = mission.vehicle_group(
            country,
            name,
            types[first.type],
            Point(first.x, first.z, mission.terrain),
            heading=math.degrees(first.heading) % 360,
        )
        vg.units[0].name = f"{name}-1"
        for number, unit in enumerate(rest, start=2):
            vehicle = mission.vehicle(f"{name}-{number}", types[unit.type])
            vehicle.position = Point(unit.x, unit.z, mission.terrain)
            vehicle.heading = math.degrees(unit.heading) % 360
            vg.add_unit(vehicle)
        rows.append({"name": name, "side": group.side, "kind": group.kind})
    return rows


def write_mission_data(game: "Game", mission: Any) -> None:
    """Called by the mission generator: the groups and their data table."""
    from game.missiongenerator.luadata import inject_data_table

    rows = generate(game, mission)
    if not rows:
        return
    inject_data_table(
        mission, "dcsRetributionGarrison", {"groups": rows}, "CTLD garrison"
    )
    logger.info("CTLD garrison: %d group(s) placed", len(rows))
