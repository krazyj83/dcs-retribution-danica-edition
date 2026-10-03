"""CTLD garrison (game/livingworld/garrison.py): troops dropped with CTLD that
survive a mission are placed again in the next one."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest
from dcs import Mission
from dcs.mapping import Point
from dcs.terrain import Caucasus

from game.livingworld import garrison
from game.livingworld.garrison import (
    BLUE,
    RED,
    GarrisonGroup,
    GarrisonUnit,
    parse_report,
    settle,
    write_mission_data,
)
from game.logistics import LogisticsManager
from game.theater.player import Player

TERRAIN = Caucasus()


def _report(*groups: Any) -> dict[str, Any]:
    return {"groups": list(groups)}


def _group(side: int = BLUE, kind: str = "troops", *units: dict[str, Any]) -> Any:
    return {"name": "Dropped Group 1", "side": side, "kind": kind, "units": list(units)}


def _unit(type_name: str = "Soldier M4", x: float = 1000, z: float = 2000) -> Any:
    return {"type": type_name, "x": x, "z": z, "heading": 1.5}


class FakeCp:
    def __init__(self, name: str, x: float, owner: Player) -> None:
        self.name = name
        self.captured = owner
        self.is_fleet = False
        self.dcs_airport = object()  # an airfield: 2.5 km base radius
        self.position = Point(x, 0, TERRAIN)


def _game(on: bool = True, ctld: bool = True) -> Any:
    lm = LogisticsManager()
    enemy = FakeCp("Sochi", 50_000, Player.RED)
    return SimpleNamespace(
        settings=SimpleNamespace(
            ctld_garrison=on, plugin_option=lambda key: ctld if key == "ctld" else None
        ),
        logistics=lm,
        theater=SimpleNamespace(terrain=TERRAIN, controlpoints=[enemy]),
        blue=SimpleNamespace(
            faction=SimpleNamespace(country=SimpleNamespace(name="USA"))
        ),
        red=SimpleNamespace(
            faction=SimpleNamespace(country=SimpleNamespace(name="Russia"))
        ),
    )


# --- the mission's report -------------------------------------------------------


def test_report_is_read_unit_by_unit() -> None:
    (group,) = parse_report(  # type: ignore[misc]
        _report(_group(BLUE, "troops", _unit("Soldier M4"), _unit("Soldier M249")))
    )
    assert (group.side, group.kind) == (BLUE, "troops")
    assert [u.type for u in group.units] == ["Soldier M4", "Soldier M249"]
    assert group.units[0] == GarrisonUnit("Soldier M4", 1000, 2000, 1.5)


@pytest.mark.parametrize("empty", [{"groups": []}, {"groups": {}}])
def test_an_empty_report_means_no_garrison(empty: Any) -> None:
    assert parse_report(empty) == []


@pytest.mark.parametrize("missing", [None, {}, "nonsense"])
def test_no_report_is_not_an_empty_one(missing: Any) -> None:
    assert parse_report(missing) is None


def test_unknown_types_and_bad_entries_are_skipped() -> None:
    groups = parse_report(
        _report(
            _group(BLUE, "troops", _unit("Some Removed Mod"), _unit("Soldier M4")),
            _group(BLUE, "troops", _unit("Some Removed Mod")),  # nothing left
            {"side": 7, "units": [_unit()]},  # no such coalition
            "junk",
        )
    )
    assert groups is not None and len(groups) == 1
    assert [u.type for u in groups[0].units] == ["Soldier M4"]


# --- debriefing -------------------------------------------------------------------


def test_the_report_replaces_the_garrison() -> None:
    game = _game()
    game.logistics._ctld_garrison = [
        GarrisonGroup(BLUE, "troops", [GarrisonUnit("Soldier M4", 0, 0)] * 6)
    ]
    log = settle(game, _report(_group(BLUE, "troops", _unit(), _unit())))
    assert [len(g.units) for g in game.logistics._ctld_garrison] == [2]
    assert "2 friendly troops and vehicles in 1 group(s)" in log[0]
    assert "(was 6)" in log[0]


def test_everyone_dead_empties_the_garrison() -> None:
    game = _game()
    game.logistics._ctld_garrison = [
        GarrisonGroup(BLUE, "troops", [GarrisonUnit("Soldier M4", 0, 0)])
    ]
    settle(game, _report())
    assert game.logistics._ctld_garrison == []


def test_no_report_keeps_the_garrison() -> None:
    game = _game()
    kept = [GarrisonGroup(BLUE, "troops", [GarrisonUnit("Soldier M4", 0, 0)])]
    game.logistics._ctld_garrison = kept
    assert settle(game, None) == []
    assert game.logistics._ctld_garrison is kept


def test_troops_inside_an_enemy_base_are_lost() -> None:
    game = _game()
    log = settle(
        game,
        _report(
            _group(BLUE, "troops", _unit(x=50_500, z=0)),  # inside Sochi
            _group(RED, "troops", _unit("Soldier AK", x=50_500, z=0)),  # its own base
        ),
    )
    assert [g.side for g in game.logistics._ctld_garrison] == [RED]
    assert any("inside enemy-held Sochi lost" in line for line in log)


def test_setting_off_ignores_the_report() -> None:
    game = _game(on=False)
    assert settle(game, _report(_group(BLUE, "troops", _unit()))) == []
    assert game.logistics._ctld_garrison == []


# --- next mission -------------------------------------------------------------------


def _mission_groups(mission: Mission) -> dict[str, Any]:
    out = {}
    for coalition in mission.coalition.values():
        for country in coalition.countries.values():
            for group in country.vehicle_group:
                out[str(group.name)] = (country.name, group)
    return out


def test_the_garrison_is_placed_where_it_stood() -> None:
    game = _game()
    game.logistics._ctld_garrison = [
        GarrisonGroup(
            BLUE,
            "troops",
            [
                GarrisonUnit("Soldier M4", 1000, 2000, math.pi / 2),
                GarrisonUnit("Soldier stinger", 1010, 2005, 0.0),
            ],
        ),
        GarrisonGroup(RED, "troops", [GarrisonUnit("Soldier AK", 5000, 5000)]),
    ]
    mission = Mission(TERRAIN)
    write_mission_data(game, mission)

    groups = _mission_groups(mission)
    country, blue = groups["CTLD Garrison 1"]
    assert country == "USA"
    assert [u.type for u in blue.units] == ["Soldier M4", "Soldier stinger"]
    assert [str(u.name) for u in blue.units] == [
        "CTLD Garrison 1-1",
        "CTLD Garrison 1-2",
    ]
    assert (blue.units[1].position.x, blue.units[1].position.y) == (1010, 2005)
    assert round(blue.units[0].heading) == 90
    assert groups["CTLD Garrison 2"][0] == "Russia"

    (trigger,) = [
        t for t in mission.triggerrules.triggers if "CTLD garrison" in str(t.comment)
    ]
    text = trigger.actions[0].dict()["text"]
    assert "dcsRetributionGarrison" in text and '"CTLD Garrison 1"' in text


@pytest.mark.parametrize("on, ctld", [(False, True), (True, False)])
def test_nothing_placed_without_the_setting_or_ctld(on: bool, ctld: bool) -> None:
    game = _game(on=on, ctld=ctld)
    game.logistics._ctld_garrison = [
        GarrisonGroup(BLUE, "troops", [GarrisonUnit("Soldier M4", 0, 0)])
    ]
    mission = Mission(TERRAIN)
    write_mission_data(game, mission)
    assert not _mission_groups(mission)


# --- saves and settings ---------------------------------------------------------


def test_old_saves_start_with_an_empty_garrison() -> None:
    state = dict(LogisticsManager().__dict__)
    state.pop("_ctld_garrison")
    restored = LogisticsManager.__new__(LogisticsManager)
    restored.__setstate__(state)
    assert restored._ctld_garrison == []


def test_setting_is_on_by_default() -> None:
    from game.settings import Settings

    assert Settings().ctld_garrison is True


def test_script_loads_after_the_state_writer() -> None:
    from game.plugins import LuaPluginManager

    base = next(
        p for p in LuaPluginManager.plugins() if p.definition.identifier == "base"
    )
    files = [w.filename for w in base.definition.work_orders]
    assert files.index("ctld_garrison.lua") > files.index("dcs_retribution.lua")
    assert garrison.GROUP_PREFIX == "CTLD Garrison"
