"""Held player convoys are released by their escort (dcs_retribution.lua),
run in Lua 5.1 against the same DCS mock as the arrival test."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.test_player_convoy_arrivals_lua import BASE, LUA, MOCK

EXTRA = r"""
flags, messages = {}, {}
coalition = {side = {RED = 1, BLUE = 2}}
trigger.action.setUserFlag = function(f, v) flags[f] = v end
trigger.action.outTextForCoalition = function(side, text) table.insert(messages, text) end
aircraft = {}
Unit = {getByName = function(name)
  local a = aircraft[name]
  if not a then return nil end
  return {
    isExist = function() return a.alive ~= false end,
    inAir = function() return a.air end,
    getPoint = function() return {x = a.x, y = 1000, z = a.z} end,
  }
end}
"""

SCENARIO = r"""
dcsRetributionPlayerConvoys = {radius = 2000, escortRadius = 9260, escortWait = 3600, convoys = {
  {group = "Player Convoy 1 - MSR", x = 50000, z = 0, flag = "convoy-go-1",
   startX = 0, startZ = 0, label = "MSR", escorts = {"Hawg 1-1", "Hawg 1-2"}},
  {group = "Player Convoy 2 - Lonely", x = 50000, z = 0, flag = "convoy-go-2",
   startX = 0, startZ = 0, label = "Lonely", escorts = {}},
  {group = "Player Convoy 3 - Free", x = 50000, z = 0},
}}
aircraft["Hawg 1-1"] = {x = 30000, z = 0, air = true}   -- 30 km out
aircraft["Hawg 1-2"] = {x = 2000, z = 0, air = false}   -- parked close by
run_until(600)
assert(flags["convoy-go-1"] == nil, "escort still far, wingman on the ground")
aircraft["Hawg 1-1"].x = 9000                           -- inside 5 nm, flying
run_until(610)
assert(flags["convoy-go-1"] == true, "released by the escort")
assert(messages[1] == "Convoy MSR: escort on station, moving out.", messages[1])
assert(flags["convoy-go-2"] == nil, "no escort yet")
run_until(3610)
assert(flags["convoy-go-2"] == true, "left alone after the wait")
assert(messages[2] == "Convoy Lonely: no escort, moving out alone.", messages[2])
assert(#messages == 2, "released once each")
print("PASS")
"""


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_escort_within_5nm_releases_the_convoy_or_it_leaves_after_an_hour(
    tmp_path: Path,
) -> None:
    script = "\n".join(
        [
            MOCK,
            EXTRA,
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
    assert "PASS" in result.stdout, result.stdout + result.stderr
