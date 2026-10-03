"""CTLD garrison mission script (resources/plugins/base/ctld_garrison.lua), run
in Lua 5.1 against a mock of DCS and CTLD. Skipped without lua5.1."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("resources/plugins/base/ctld_garrison.lua")
JSON = Path("resources/plugins/base/json.lua")
LUA = shutil.which("lua5.1") or shutil.which("luajit")
pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")

MOCK = r"""
logs = {}
env = { info = function(m) table.insert(logs, m) end }
scheduled = {}
timer = {
  getTime = function() return 0 end,
  scheduleFunction = function(f, arg, t) table.insert(scheduled, {f = f, arg = arg, t = t}) end,
}
-- units: name -> {type, x, z, alive}; groups: name -> list of unit names
local units, groups = {}, {}
function unit(name, type_name, x, z, alive)
  units[name] = {type = type_name, x = x, z = z, alive = alive ~= false}
end
function group(name, unit_names) groups[name] = unit_names end
local function make_unit(name)
  local u = units[name]
  return {
    isExist = function() return u.alive end,
    getLife = function() return u.alive and 1 or 0 end,
    getPoint = function() return {x = u.x, y = 0, z = u.z} end,
    getPosition = function() return {x = {x = 0, y = 0, z = 1}} end,  -- facing east
    getTypeName = function() return u.type end,
  }
end
Group = {
  getByName = function(name)
    local names = groups[name]
    if not names then return nil end
    return {
      isExist = function() return true end,
      getUnits = function()
        local out = {}
        for _, n in ipairs(names) do out[#out + 1] = make_unit(n) end
        return out
      end,
    }
  end,
}
function start_ctld()
  ctld = {droppedTroopsBLUE = {}, droppedTroopsRED = {}, droppedVehiclesBLUE = {}, droppedVehiclesRED = {}}
end
function check(cond, what) if not cond then error("FAILED: " .. what, 2) end end
function run_scheduled()
  local s = scheduled; scheduled = {}
  for _, job in ipairs(s) do
    local again = job.f(job.arg, job.t)
    if again then table.insert(scheduled, {f = job.f, arg = job.arg, t = again}) end
  end
end
"""


def _run(scenario: str) -> str:
    assert LUA is not None
    code = (
        MOCK
        + JSON.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
        + "\n"
        + scenario
        + '\nprint("PASS")\n'
    )
    result = subprocess.run(
        [LUA, "-"], input=code, capture_output=True, text=True, timeout=30
    )
    assert "PASS" in result.stdout, result.stdout + result.stderr
    return result.stdout


def test_living_ctld_groups_are_reported_unit_by_unit() -> None:
    out = _run(r"""
start_ctld()
unit("t1", "Soldier M4", 100, 200); unit("t2", "Soldier M249", 110, 205)
unit("t3", "Soldier M4", 0, 0, false)                     -- killed
group("Dropped Group 1", {"t1", "t2", "t3"})
unit("r1", "Soldier AK", 900, 900); group("Dropped Group 2", {"r1"})
group("Extracted Group", {})                               -- picked up again
table.insert(ctld.droppedTroopsBLUE, "Dropped Group 1")
table.insert(ctld.droppedTroopsBLUE, "Dropped Group 1")   -- listed twice
table.insert(ctld.droppedTroopsBLUE, "Extracted Group")
table.insert(ctld.droppedTroopsBLUE, "Gone Group")         -- destroyed
table.insert(ctld.droppedTroopsRED, "Dropped Group 2")
print(json:encode(retribution_ctld_garrison_state()))
""")
    report = json.loads(out.splitlines()[0])
    blue, red = report["groups"]
    assert (blue["side"], blue["kind"], red["side"]) == (2, "troops", 1)
    assert [u["type"] for u in blue["units"]] == ["Soldier M4", "Soldier M249"]
    assert (blue["units"][0]["x"], blue["units"][0]["z"]) == (100, 200)
    assert abs(blue["units"][0]["heading"] - 1.5708) < 0.001  # east


def test_no_ctld_means_no_report() -> None:
    _run(r"""
check(retribution_ctld_garrison_state() == nil, "nil without CTLD")
""")


def test_an_empty_garrison_is_still_a_report() -> None:
    out = _run(r"""
start_ctld()
print(json:encode(retribution_ctld_garrison_state()))
""")
    assert json.loads(out.splitlines()[0])["groups"] in ([], {})


def test_placed_groups_are_handed_to_ctld_once_it_runs() -> None:
    _run(r"""
dcsRetributionGarrison = {groups = {
  {name = "CTLD Garrison 1", side = 2, kind = "troops"},
  {name = "CTLD Garrison 2", side = 1, kind = "vehicles"},
  {name = "CTLD Garrison 3", side = 2, kind = "troops"},   -- not in the mission
}}
unit("g1", "Soldier M4", 0, 0); group("CTLD Garrison 1", {"g1"})
unit("g2", "M1043 HMMWV Armament", 0, 0); group("CTLD Garrison 2", {"g2"})
check(#scheduled == 1, "hand-back scheduled")
run_scheduled()                                -- CTLD not started yet: retry
check(#scheduled == 1, "retried")
start_ctld()
run_scheduled()
check(#scheduled == 0, "done")
check(ctld.droppedTroopsBLUE[1] == "CTLD Garrison 1", "blue troops handed back")
check(ctld.droppedVehiclesRED[1] == "CTLD Garrison 2", "red vehicles handed back")
check(#ctld.droppedTroopsBLUE == 1, "missing group skipped")
""")
