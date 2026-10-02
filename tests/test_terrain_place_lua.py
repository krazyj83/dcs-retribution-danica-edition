"""Terrain placement at mission start (resources/plugins/base/terrain_place.lua),
run in Lua 5.1 against a mock of the DCS terrain.

The mock map (x north, y east, metres):

    a steep ridge   0 <= x <= 200        height rises 0.5 m per metre (27 deg)
    a road          -10 <= y <= 10        (east-west band through the middle)
    a lake          x <= -2000
    everything else flat land

Skipped when no lua5.1 interpreter is installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("resources/plugins/base/terrain_place.lua")
LUA = shutil.which("lua5.1") or shutil.which("luajit")
pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")

MOCK = r"""
logs = {}
env = {
  info = function(m) table.insert(logs, m) end,
  warning = function(m) table.insert(logs, "WARN " .. m) end,
}
land = {SurfaceType = {LAND = 1, SHALLOW_WATER = 2, WATER = 3, ROAD = 4, RUNWAY = 5}}
function land.getHeight(p)
  if p.x >= 0 and p.x <= 200 then return p.x * 0.5 end
  if p.x > 200 then return 100 end
  return 0
end
function land.getSurfaceType(p)
  if p.x <= -2000 then return land.SurfaceType.WATER end
  if p.y >= -10 and p.y <= 10 then return land.SurfaceType.ROAD end
  return land.SurfaceType.LAND
end
groups, added = {}, {}
mist = {
  getGroupData = function(name)
    local g = groups[name]
    if not g then return nil end
    local copy = {name = name, units = {}, route = {points = {}}}
    for i, u in ipairs(g) do
      copy.units[i] = {unitName = name .. "-" .. i, x = u[1], y = u[2]}
    end
    copy.route.points[1] = {x = g[1][1], y = g[1][2]}
    return copy
  end,
  dynAdd = function(data) added[data.name] = data end,
}
function check(cond, what) if not cond then error("FAILED: " .. what, 2) end end
function has_log(pat)
  for _, m in ipairs(logs) do if string.find(m, pat, 1, true) then return true end end
  return false
end
TerrainPlace = {no_autorun = true}
function site(name, role, ...)
  local names = {...}
  if #names == 0 then names = {name} end
  table.insert(dcsRetributionTerrain.sites, {name = name, role = role, groups = names})
end
"""


def _run(scenario: str) -> str:
    assert LUA is not None
    code = MOCK + SCRIPT.read_text() + "\n" + scenario + '\nprint("PASS")\n'
    result = subprocess.run(
        [LUA, "-"], input=code, capture_output=True, text=True, timeout=30
    )
    assert "PASS" in result.stdout, result.stdout + result.stderr
    return result.stdout


DATA = r"""
dcsRetributionTerrain = {
  sites = {}, towns = {{name = "KUTAISI", x = 5000, y = 5000, r = 500}},
  maxSlope = 0.2, searchMax = 1200,
}
"""


def test_a_group_on_flat_ground_is_left_alone() -> None:
    _run(DATA + r"""
groups["SAM flat"] = {{1000, 1000}, {1040, 1000}, {1000, 1040}}
site("SAM flat", "sam")
check(TerrainPlace.run() == 0, "nothing moved")
check(added["SAM flat"] == nil, "not re-added")
""")


def test_a_group_on_a_steep_ridge_moves_off_it_as_a_whole() -> None:
    _run(DATA + r"""
groups["SAM ridge"] = {{100, 1000}, {140, 1000}, {100, 1040}}
site("SAM ridge", "sam")
check(TerrainPlace.run() == 1, "one group moved")
local g = added["SAM ridge"]
check(g ~= nil, "re-added under the same name")
check(g.units[1].unitName == "SAM ridge-1", "unit names kept")
-- every unit off the ridge (x < 0 - probe, or x > 200 + probe)
for _, u in ipairs(g.units) do
  check(u.x < -8 or u.x > 208, "unit off the ridge, x=" .. u.x)
end
-- layout kept: same offsets between units
check(math.abs((g.units[2].x - g.units[1].x) - 40) < 0.01, "layout x kept")
check(math.abs((g.units[3].y - g.units[1].y) - 40) < 0.01, "layout y kept")
check(g.route.points[1].x == g.units[1].x, "spawn point moved with it")
check(has_log("moved SAM ridge"), "logged")
check(has_log("3 on slope"), "reason logged")
""")


def test_a_parked_group_on_a_road_moves_off_it() -> None:
    _run(DATA + r"""
groups["Motorpool"] = {{1000, 0}, {1020, 5}}
site("Motorpool", "parked")
TerrainPlace.run()
local g = added["Motorpool"]
check(g ~= nil, "moved")
for _, u in ipairs(g.units) do
  check(math.abs(u.y) > 10, "off the road, y=" .. u.y)
end
""")


def test_sams_leave_town_centres_but_parked_units_may_stay() -> None:
    _run(DATA + r"""
groups["SAM town"] = {{5100, 5100}, {5120, 5100}}
groups["Depot trucks"] = {{4900, 4900}}
site("SAM town", "sam")
site("Depot trucks", "parked")
check(TerrainPlace.run() == 1, "only the SAM moved")
local g = added["SAM town"]
local cx, cy = (g.units[1].x + g.units[2].x) / 2, (g.units[1].y + g.units[2].y) / 2
local d = math.sqrt((cx - 5000) ^ 2 + (cy - 5000) ^ 2)
check(d >= 500, "out of the town centre, d=" .. d)
check(added["Depot trucks"] == nil, "parked group not moved for a town")
check(has_log("town KUTAISI"), "town named in the log")
""")


def test_nothing_better_within_range_leaves_the_group() -> None:
    _run(r"""
dcsRetributionTerrain = {sites = {}, towns = {}, maxSlope = 0.2, searchMax = 120}
-- 1 km wide ridge: no flat ground within 120 m
function land.getHeight(p) return p.x * 0.5 end
groups["SAM hill"] = {{500, 500}}
site("SAM hill", "sam")
check(TerrainPlace.run() == 0, "not moved")
check(added["SAM hill"] == nil, "not re-added")
check(has_log("no better spot within 120 m"), "logged")
""")


def test_a_better_but_not_perfect_spot_is_still_taken() -> None:
    _run(r"""
dcsRetributionTerrain = {sites = {}, towns = {}, maxSlope = 0.2, searchMax = 300}
-- 3 units on the ridge; within 300 m only spots with fewer bad units exist
groups["SAM wide"] = {{100, 1000}, {150, 1000}, {300, 1000}}
site("SAM wide", "sam")
local before = TerrainPlace.score(mist.getGroupData("SAM wide").units, "sam", 0, 0, dcsRetributionTerrain)
check(before == 2, "two units on the ridge, got " .. before)
TerrainPlace.run()
local g = added["SAM wide"]
check(g ~= nil, "moved")
local after = TerrainPlace.score(g.units, "sam", 0, 0, dcsRetributionTerrain)
check(after < before, "better than before: " .. after)
""")


def test_missing_data_and_missing_groups_are_harmless() -> None:
    _run(r"""
dcsRetributionTerrain = nil
check(TerrainPlace.run() == 0, "no data: nothing to do")
dcsRetributionTerrain = {sites = {{name = "Gone", role = "sam", groups = {"Gone"}}}, towns = {}}
check(TerrainPlace.run() == 0, "unknown group skipped")
mist.getGroupData = function() error("boom") end
dcsRetributionTerrain = {sites = {{name = "Broken", role = "sam", groups = {"Broken"}}}, towns = {}}
check(TerrainPlace.run() == 0, "error caught")
check(has_log("WARN terrain_place: Broken"), "error logged")
""")


def test_all_groups_of_a_site_move_together() -> None:
    _run(DATA + r"""
-- radar on the ridge, launchers and AAA beside it on flat ground
groups["Hawk radar"] = {{150, 1000}}
groups["Hawk launchers"] = {{260, 1000}, {260, 1060}}
groups["Hawk AAA"] = {{320, 1000}}
site("Hawk site", "sam", "Hawk radar", "Hawk launchers", "Hawk AAA")
check(TerrainPlace.run() == 1, "one site moved")
local r, l, a = added["Hawk radar"], added["Hawk launchers"], added["Hawk AAA"]
check(r and l and a, "every group of the site re-added")
local dx, dy = r.units[1].x - 150, r.units[1].y - 1000
check(math.abs((l.units[1].x - 260) - dx) < 0.01 and math.abs((l.units[1].y - 1000) - dy) < 0.01, "launchers same offset")
check(math.abs((a.units[1].x - 320) - dx) < 0.01, "AAA same offset")
check(r.units[1].x > 208, "radar off the ridge")
check(has_log("moved Hawk site"), "logged by site name")
""")
