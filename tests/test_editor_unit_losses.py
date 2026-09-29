"""Losses of units added to the generated mission in the mission editor."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from dcs.countries import USA, Russia
from dcs.mission import Mission
from dcs.terrain import Caucasus
from dcs.vehicles import Armor

from game.debriefing import Debriefing, StateData
from game.theater import Player
from game.unitmap import UnitMap

BASE = Path("resources/plugins/base")
LUA = shutil.which("lua5.1") or shutil.which("luajit")


def test_generated_unit_names_cover_every_group_type() -> None:
    mission = Mission(Caucasus())
    usa = mission.country(USA.name)
    russia = mission.country(Russia.name)
    tbilisi = mission.terrain.airports["Tbilisi-Lochini"].position
    mission.vehicle_group(usa, "Blue armour", Armor.M_1_Abrams, tbilisi, group_size=2)
    mission.vehicle_group(russia, "Red armour", Armor.T_72B3, tbilisi)
    unit_map = UnitMap()

    unit_map.record_generated_units(mission)

    names = unit_map.generated_unit_names
    assert names is not None and len(names) == 3
    assert all(isinstance(n, str) for n in names)


def _debriefing(losses: list[dict[str, Any]], generated: Any) -> Debriefing:
    debriefing = Debriefing.__new__(Debriefing)
    debriefing.state_data = StateData.from_json(
        {"miz_unit_losses": losses}, SimpleNamespace(flight=lambda name: None)  # type: ignore[arg-type]
    )
    debriefing.unit_map = SimpleNamespace(generated_unit_names=generated)  # type: ignore[assignment]
    debriefing.air_losses = SimpleNamespace(player=[], enemy=[])  # type: ignore[assignment]
    from game.debriefing import GroundLosses

    debriefing.ground_losses = GroundLosses()
    debriefing.base_captures = []
    debriefing.editor_losses = debriefing.dead_editor_units()
    return debriefing


LOSSES = [
    {"name": "Ret tank 1", "coalition": "red", "category": "vehicle", "type": "T-72B3"},
    {"name": "My Su-30", "coalition": "red", "category": "plane", "type": "Su-30"},
    {
        "name": "My SA-15",
        "coalition": "red",
        "category": "vehicle",
        "type": "Tor 9A331",
    },
    {
        "name": "My Tor 2",
        "coalition": "red",
        "category": "vehicle",
        "type": "Tor 9A331",
    },
    {"name": "My Hummer", "coalition": "blue", "category": "vehicle", "type": "Hummer"},
    {
        "name": "Neutral truck",
        "coalition": "neutrals",
        "category": "vehicle",
        "type": "x",
    },
]


def test_editor_losses_counted_per_side_and_type() -> None:
    debriefing = _debriefing(LOSSES, frozenset({"Ret tank 1"}))

    assert debriefing.loss_counts(Player.RED).editor_units == 3
    assert debriefing.loss_counts(Player.BLUE).editor_units == 1
    assert debriefing.editor_losses_by_type(Player.RED) == {
        "Su-30": 1,
        "Tor 9A331": 2,
    }


def test_nothing_counted_without_the_generated_names() -> None:
    # Mission not generated in this session: we can't tell editor units apart.
    debriefing = _debriefing(LOSSES, None)
    assert debriefing.editor_losses == []
    assert debriefing.loss_counts(Player.RED).editor_units == 0


MOCK = r"""
local handlers = {}
timer = {getTime = function() return 0 end, scheduleFunction = function() end}
env = {info = function() end, mission = {coalition = {
  blue = {country = {{vehicle = {group = {{units = {{name = "Ret Abrams", type = "M-1 Abrams"}}}}}}}},
  red = {country = {{
    plane = {group = {{units = {{name = "My Su-30", type = "Su-30"}}}}},
    vehicle = {group = {{units = {{name = "My Tor", type = "Tor 9A331"}, {name = "Alive", type = "Tor 9A331"}}}}},
  }}},
}}}
mist = {
  Logger = {new = function() return {info = function() end, error = function() end} end},
  addEventHandler = function(f) table.insert(handlers, f) end,
  scheduleFunction = function() end,
  getHeading = function() return 0 end,
}
world = {event = {S_EVENT_CRASH = 5, S_EVENT_DEAD = 8, S_EVENT_UNIT_LOST = 30, S_EVENT_KILL = 29, S_EVENT_MISSION_END = 12}}
trigger = {action = {outText = function() end}}
AI = {Option = {Air = {val = {ROE = {}}}}}
function obj(name)
  return {
    getName = function() return name end,
    getPosition = function() return {p = {x = 0, y = 0, z = 0}} end,
    getTypeName = function() return "x" end,
  }
end
function fire(id, initiator, target)
  for _, h in ipairs(handlers) do h({id = id, initiator = initiator, target = target}) end
end
"""

SCENARIO = r"""
fire(world.event.S_EVENT_DEAD, obj("Ret Abrams"))
fire(world.event.S_EVENT_CRASH, obj("My Su-30"))
fire(world.event.S_EVENT_KILL, obj("Shooter"), obj("My Tor"))
fire(world.event.S_EVENT_DEAD, obj("My Tor"))          -- same unit again
fire(world.event.S_EVENT_DEAD, obj("CTLD troops #4"))  -- spawned at runtime
write_state()
"""


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_mission_script_reports_mission_file_units_lost(tmp_path: Path) -> None:
    script = "\n".join(
        [
            MOCK,
            f'os.getenv = function(k) if k == "RETRIBUTION_EXPORT_DIR" then '
            f'return "{tmp_path.as_posix()}/" end return nil end',
            (BASE / "json.lua").read_text(encoding="utf-8"),
            (BASE / "dcs_retribution.lua").read_text(encoding="utf-8"),
            SCENARIO,
        ]
    )
    runner = tmp_path / "run.lua"
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(LUA), str(runner)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr

    (written,) = list(tmp_path.glob("*state.json"))
    state = json.loads(written.read_text(encoding="utf-8"))
    losses = {loss["name"]: loss for loss in state["miz_unit_losses"]}
    assert sorted(losses) == ["My Su-30", "My Tor", "Ret Abrams"]
    assert losses["My Su-30"] == {
        "name": "My Su-30",
        "coalition": "red",
        "category": "plane",
        "type": "Su-30",
    }


SHOT_SCENARIO = r"""
local function weapon(t) return {getTypeName = function() return t end} end
fire_shot = function(unit, t)
  for _, h in ipairs(handlers) do
    h({id = world.event.S_EVENT_SHOT, initiator = obj(unit), weapon = weapon(t)})
  end
end
fire_shot("Viper 1-1", "AIM_120C")
fire_shot("Viper 1-1", "AIM_120C")
fire_shot("Viper 1-1", "GBU_12")
write_state()
"""


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_mission_script_reports_weapons_fired(tmp_path: Path) -> None:
    mock = MOCK.replace(
        "S_EVENT_MISSION_END = 12", "S_EVENT_MISSION_END = 12, S_EVENT_SHOT = 1"
    )
    script = "\n".join(
        [
            mock,
            f'os.getenv = function(k) if k == "RETRIBUTION_EXPORT_DIR" then '
            f'return "{tmp_path.as_posix()}/" end return nil end',
            (BASE / "json.lua").read_text(encoding="utf-8"),
            (BASE / "dcs_retribution.lua").read_text(encoding="utf-8"),
            SHOT_SCENARIO,
        ]
    )
    runner = tmp_path / "run.lua"
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(LUA), str(runner)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    (written,) = list(tmp_path.glob("*state.json"))
    state = json.loads(written.read_text(encoding="utf-8"))
    assert state["weapons_fired"] == {"Viper 1-1": {"AIM_120C": 2, "GBU_12": 1}}
