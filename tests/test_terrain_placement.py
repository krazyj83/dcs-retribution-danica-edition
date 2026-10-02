"""Terrain placement mission data (game/livingworld/terrain.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dcs import Mission
from dcs.mapping import Point
from dcs.terrain import Caucasus
from dcs.vehicles import AirDefence, Armor

from game.livingworld import terrain
from game.livingworld.terrain import (
    TOWN_CENTRE_RADIUS,
    load_towns,
    nearby_towns,
    parse_towns,
    placement_sites,
    script_data,
    towns_file,
)
from game.plugins import LuaPluginManager

TOWNS_LUA = """local gettext = require("i_18n")
local       _ = gettext.translate

towns = {
["KUTAISI"] = { latitude = 42.267086, longitude = 42.696849, display_name = _("KUTAISI")},
["BATUMI"] = { latitude = 41.654059, longitude = 41.655372, display_name = _("BATUMI")},
["ST. GEORGE"] = { latitude = -51.70, longitude = -57.85, display_name = _("ST. GEORGE")},
}
"""


def _install(tmp_path: Path, folder: str, sub: str = "Map") -> Path:
    path = tmp_path / "Mods" / "terrains" / folder / sub
    path.mkdir(parents=True)
    (path / "towns.lua").write_text(TOWNS_LUA, encoding="utf-8")
    return tmp_path


def test_parse_towns() -> None:
    towns = parse_towns(TOWNS_LUA)
    assert towns[0] == ("KUTAISI", 42.267086, 42.696849)
    assert [t[0] for t in towns] == ["KUTAISI", "BATUMI", "ST. GEORGE"]
    assert towns[2][1] < 0  # southern hemisphere


def test_towns_file_maps_terrain_names_to_folders(tmp_path: Path) -> None:
    install = _install(tmp_path, "GermanyColdWar", sub="map")
    assert towns_file(str(install), "GermanyCW") is not None
    assert towns_file(str(install), "Caucasus") is None
    assert towns_file("", "Caucasus") is None
    assert load_towns(str(tmp_path / "nowhere"), "Caucasus") == []


def test_only_towns_near_groups_are_sent() -> None:
    caucasus = Caucasus()
    kutaisi = Point.from_latlng(
        __import__("dcs.mapping", fromlist=["LatLng"]).LatLng(42.267086, 42.696849),
        caucasus,
    )
    towns = nearby_towns(
        parse_towns(TOWNS_LUA), caucasus, [(kutaisi.x + 1500, kutaisi.y)]
    )
    assert [t["name"] for t in towns] == ["KUTAISI"]
    assert towns[0]["r"] == TOWN_CENTRE_RADIUS
    assert abs(towns[0]["x"] - kutaisi.x) <= 1


def _mission_with_groups() -> Any:
    mission = Mission(Caucasus())
    usa = mission.country("USA")
    mission.vehicle_group(
        usa, "SAM site", AirDefence.Hawk_ln, Point(0, 0, mission.terrain)
    )
    mission.vehicle_group(
        usa, "Motorpool 1", Armor.M_1_Abrams, Point(500, 0, mission.terrain)
    )
    return mission


class SamGroundObject:  # stand-ins named like the real classes
    def __init__(self, name: str, *groups: str) -> None:
        self.name = name
        self.groups = [SimpleNamespace(group_name=n) for n in groups]


class MotorpoolGroundObject(SamGroundObject):
    pass


def _game(mission: Any) -> Any:
    cp = SimpleNamespace(
        ground_objects=[
            SamGroundObject("Kutaisi SAM", "SAM site", "Not in the mission"),
            MotorpoolGroundObject("Motorpool", "Motorpool 1"),
            SamGroundObject("Destroyed SAM", "Gone"),
        ]
    )
    return SimpleNamespace(
        theater=SimpleNamespace(controlpoints=[cp], terrain=mission.terrain),
        settings=SimpleNamespace(terrain_placement=True),
    )


def test_sites_get_their_role_and_groups() -> None:
    mission = _mission_with_groups()
    assert placement_sites(_game(mission), mission) == [
        {"name": "Kutaisi SAM", "role": "sam", "groups": ["SAM site"]},
        {"name": "Motorpool", "role": "parked", "groups": ["Motorpool 1"]},
    ]  # groups not in the mission (destroyed) are left out


def test_script_data_without_a_dcs_install() -> None:
    mission = _mission_with_groups()
    data = script_data(_game(mission), mission, "")
    assert data["sites"][0]["groups"] == ["SAM site"]
    assert data["towns"] == []
    assert data["maxSlope"] == 0.2 and data["searchMax"] == 1200


def test_written_into_the_mission_only_with_the_setting(monkeypatch: Any) -> None:
    from game.missiongenerator.luadata import DATA_TRIGGER_PREFIX

    mission = _mission_with_groups()
    game = _game(mission)
    game.settings.terrain_placement = False
    terrain.write_mission_data(game, mission)
    assert not any("terrain" in str(t.comment) for t in mission.triggerrules.triggers)

    game.settings.terrain_placement = True
    terrain.write_mission_data(game, mission)
    (trigger,) = [
        t for t in mission.triggerrules.triggers if "terrain" in str(t.comment)
    ]
    assert str(trigger.comment).startswith(DATA_TRIGGER_PREFIX)
    assert "dcsRetributionTerrain" in trigger.actions[0].dict()["text"]


def test_script_loads_after_mist_in_the_base_plugin() -> None:
    base = next(
        p for p in LuaPluginManager.plugins() if p.definition.identifier == "base"
    )
    files = [w.filename for w in base.definition.work_orders]
    assert files.index("terrain_place.lua") > files.index("mist_4_5_126.lua")
    assert files.index("terrain_place.lua") > files.index("water_relocate.lua")


def test_dcs_install_dir_is_remembered() -> None:
    from game import persistency

    old = persistency.dcs_install_dir()
    try:
        persistency.set_dcs_install_dir("D:\\DCS World")
        assert persistency.dcs_install_dir() == "D:\\DCS World"
        persistency.set_dcs_install_dir(None)  # type: ignore[arg-type]
        assert persistency.dcs_install_dir() == ""
    finally:
        persistency.set_dcs_install_dir(old)
