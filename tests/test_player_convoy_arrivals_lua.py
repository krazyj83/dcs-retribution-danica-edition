"""Player convoy arrival detection in the mission script
(resources/plugins/base/dcs_retribution.lua), run in Lua 5.1 against a mock of
the DCS API. The written state.json is read back like the debrief does.

Skipped when no lua5.1 interpreter is installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASE = Path("resources/plugins/base")
LUA = shutil.which("lua5.1") or shutil.which("luajit")

MOCK = r"""
local now = 0
local scheduled = {}
timer = {
  getTime = function() return now end,
  scheduleFunction = function(f, arg, t) table.insert(scheduled, {f = f, arg = arg, t = t}) end,
}
function run_until(t)
  while true do
    table.sort(scheduled, function(a, b) return a.t < b.t end)
    local job = scheduled[1]
    if not job or job.t > t then break end
    table.remove(scheduled, 1)
    now = job.t
    local ok, nxt = pcall(job.f, job.arg, now)
    if ok and nxt then table.insert(scheduled, {f = job.f, arg = job.arg, t = nxt}) end
  end
  now = t
end
env = {info = function() end}
mist = {
  Logger = {new = function() return {info = function() end, error = function() end} end},
  addEventHandler = function() end,
  scheduleFunction = function() end,
}
world = {event = {}}
trigger = {action = {outText = function() end}}
AI = {Option = {Air = {val = {ROE = {}}}}}

-- Vehicles: name -> {x, z, alive}
vehicles = {}
local function unit(name)
  return {
    getName = function() return name end,
    isExist = function() return vehicles[name].alive end,
    getLife = function() return vehicles[name].alive and 1 or 0 end,
    getPoint = function() return {x = vehicles[name].x, y = 0, z = vehicles[name].z} end,
  }
end
groups = {}
Group = {getByName = function(name)
  local members = groups[name]
  if not members then return nil end
  return {
    isExist = function() return true end,
    getUnits = function()
      local list = {}
      for _, n in ipairs(members) do
        if vehicles[n].alive then table.insert(list, unit(n)) end
      end
      return list
    end,
  }
end}
"""

SCENARIO = r"""
dcsRetributionPlayerConvoys = {radius = 2000, convoys = {
  {group = "Player Convoy 1 - MSR", x = 10000, z = 0},
}}
groups["Player Convoy 1 - MSR"] = {"Truck 1", "Truck 2", "Tank 3"}
vehicles["Truck 1"] = {x = 0, z = 0, alive = true}
vehicles["Truck 2"] = {x = 0, z = 0, alive = true}
vehicles["Tank 3"] = {x = 0, z = 0, alive = true}

run_until(60)                                  -- still at the start
vehicles["Truck 1"].x = 9000                   -- 1 km from the end: arrived
vehicles["Tank 3"].x = 9000
run_until(120)
vehicles["Tank 3"].alive = false               -- killed after arriving
vehicles["Truck 2"].x = 5000                   -- halfway at mission end
run_until(180)
write_state()
"""


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_only_vehicles_that_reached_the_route_end_are_reported(
    tmp_path: Path,
) -> None:
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

    written = list(tmp_path.glob("*state.json"))
    assert written, "write_state did not write a state file"
    state = json.loads(written[0].read_text(encoding="utf-8"))
    # Truck 1 arrived; Tank 3 arrived (its death is settled from the dead
    # events); Truck 2 never got there.
    assert sorted(state["player_convoy_arrivals"]) == ["Tank 3", "Truck 1"]


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_no_convoys_writes_no_arrivals(tmp_path: Path) -> None:
    script = "\n".join(
        [
            MOCK,
            f'os.getenv = function(k) if k == "RETRIBUTION_EXPORT_DIR" then '
            f'return "{tmp_path.as_posix()}/" end return nil end',
            (BASE / "json.lua").read_text(encoding="utf-8"),
            (BASE / "dcs_retribution.lua").read_text(encoding="utf-8"),
            "run_until(60)\nwrite_state()",
        ]
    )
    runner = tmp_path / "run.lua"
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(LUA), str(runner)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(next(tmp_path.glob("*state.json")).read_text("utf-8"))
    assert "player_convoy_arrivals" not in state
