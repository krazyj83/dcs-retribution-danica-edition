"""Terrain placement: what the mission script needs to keep parked ground
units off steep slopes, off roads and out of town centres.

Retribution can't see the DCS terrain (heights and road surfaces are only
available inside DCS), so the checks run in the mission at start-up
(resources/plugins/base/terrain_place.lua). This module writes the mission
data that script reads:

    dcsRetributionTerrain = {
        sites  = { { name = "Kutaisi SAM", role = "sam",
                     groups = { "Kutaisi SAM 1", "Kutaisi SAM 2" } }, ... },
        towns  = { { name = "KUTAISI", x = -284000, y = 683000, r = 500 }, ... },
        maxSlope = 0.2, searchMax = 1200,
    }

Sites: the ground objects (SAM and EWR sites, armour, missile and coastal
sites, motorpools) with their vehicle groups. A site's groups (a SAM's radar,
launchers and protecting AAA) are always moved together, so the site keeps
its layout. Front-line units, convoys and ships move, so they're left alone.

Towns: read from the player's own DCS install
(<DCS>/Mods/terrains/<map>/Map/towns.lua, names and positions only) when the
mission is generated, so no DCS data is copied into the repo. Only towns near
a listed group are sent.
"""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Town centre radius (m). towns.lua has positions but no sizes, so every
#: town gets the same centre; SAMs, EWRs and armour are kept out of it.
TOWN_CENTRE_RADIUS = 500
#: Towns further than this from every listed group aren't sent.
TOWN_SEARCH_RADIUS = 3000
#: Slope (rise over run) above which a unit counts as on a steep slope:
#: 0.2 is about 11 degrees.
MAX_SLOPE = 0.2
#: How far (m) the script may move a group.
SEARCH_MAX = 1200

#: Ground object kind -> role in the script. Only "sam", "ewr", "armor" and
#: "site" are kept out of towns; every role is kept off slopes and roads.
ROLES = {
    "SamGroundObject": "sam",
    "EwrGroundObject": "ewr",
    "VehicleGroupGroundObject": "armor",
    "MissileSiteGroundObject": "site",
    "CoastalSiteGroundObject": "site",
}
TOWN_ROLES = frozenset({"sam", "ewr", "armor", "site"})

#: pydcs terrain name -> folder under <DCS>/Mods/terrains, where different.
TERRAIN_FOLDERS = {
    "GermanyCW": "GermanyColdWar",
    "SinaiMap": "Sinai",
}

_TOWN_LINE = re.compile(
    r'\[\s*"([^"]+)"\s*\]\s*=\s*\{[^}]*?latitude\s*=\s*(-?[\d.]+)\s*,'
    r"\s*longitude\s*=\s*(-?[\d.]+)"
)


def towns_file(install_dir: str, terrain_name: str) -> Optional[Path]:
    """<DCS>/Mods/terrains/<map>/Map/towns.lua, or None if not installed."""
    if not install_dir:
        return None
    folder = Path(install_dir) / "Mods" / "terrains"
    folder = folder / TERRAIN_FOLDERS.get(terrain_name, terrain_name)
    for sub in ("Map", "map"):
        path = folder / sub / "towns.lua"
        if path.is_file():
            return path
    return None


def parse_towns(text: str) -> List[Tuple[str, float, float]]:
    """(name, latitude, longitude) of every town in a towns.lua."""
    return [
        (m.group(1), float(m.group(2)), float(m.group(3)))
        for m in _TOWN_LINE.finditer(text)
    ]


@lru_cache(maxsize=16)
def _towns_cached(path: str) -> Tuple[Tuple[str, float, float], ...]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        logging.exception("Terrain placement: can't read %s", path)
        return ()
    return tuple(parse_towns(text))


def load_towns(install_dir: str, terrain_name: str) -> List[Tuple[str, float, float]]:
    path = towns_file(install_dir, terrain_name)
    if path is None:
        return []
    return list(_towns_cached(str(path)))


def _role(ground_object: Any) -> str:
    return ROLES.get(type(ground_object).__name__, "parked")


def placement_sites(game: Any, mission: Any) -> List[Dict[str, Any]]:
    """Every ground object with vehicle groups in the mission: its name, role
    and group names."""
    from dcs.unitgroup import VehicleGroup

    sites: List[Dict[str, Any]] = []
    for cp in game.theater.controlpoints:
        for ground_object in cp.ground_objects:
            names = [
                group.group_name
                for group in ground_object.groups
                if isinstance(mission.find_group(group.group_name), VehicleGroup)
            ]
            if names:
                sites.append(
                    {
                        "name": str(getattr(ground_object, "name", names[0])),
                        "role": _role(ground_object),
                        "groups": names,
                    }
                )
    return sites


def _group_positions(mission: Any, names: List[str]) -> List[Tuple[float, float]]:
    points = []
    for name in names:
        group = mission.find_group(name)
        if group is not None and group.units:
            points.append((group.units[0].position.x, group.units[0].position.y))
    return points


def nearby_towns(
    towns: List[Tuple[str, float, float]],
    terrain: Any,
    points: List[Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """Towns within TOWN_SEARCH_RADIUS of any point, in mission coordinates."""
    from dcs.mapping import LatLng, Point

    result = []
    for name, lat, lon in towns:
        p = Point.from_latlng(LatLng(lat, lon), terrain)
        if any(math.hypot(p.x - x, p.y - y) <= TOWN_SEARCH_RADIUS for x, y in points):
            result.append(
                {
                    "name": name,
                    "x": round(p.x),
                    "y": round(p.y),
                    "r": TOWN_CENTRE_RADIUS,
                }
            )
    return result


def script_data(game: Any, mission: Any, install_dir: str) -> Dict[str, Any]:
    """The dcsRetributionTerrain table."""
    sites = placement_sites(game, mission)
    town_groups = [
        name for site in sites if site["role"] in TOWN_ROLES for name in site["groups"]
    ]
    towns = nearby_towns(
        load_towns(install_dir, game.theater.terrain.name),
        game.theater.terrain,
        _group_positions(mission, town_groups),
    )
    return {
        "sites": sites,
        "towns": towns,
        "maxSlope": MAX_SLOPE,
        "searchMax": SEARCH_MAX,
    }


def write_mission_data(game: Any, mission: Any) -> None:
    """Called by the mission generator after the ground objects exist."""
    from game import persistency
    from game.missiongenerator.luadata import inject_data_table

    if not getattr(game.settings, "terrain_placement", False):
        return
    data = script_data(game, mission, persistency.dcs_install_dir())
    inject_data_table(mission, "dcsRetributionTerrain", data, "terrain placement")
    logging.info(
        "Terrain placement: %d sites, %d towns nearby",
        len(data["sites"]),
        len(data["towns"]),
    )
