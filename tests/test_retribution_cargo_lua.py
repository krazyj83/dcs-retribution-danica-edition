"""The F10 cargo menu script, run in Lua 5.1 against a mock of the DCS API.

Skipped when no lua5.1 interpreter is installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("resources/plugins/base/retribution_cargo.lua")
JSON_LIB = Path("resources/plugins/base/json.lua")
LUA = shutil.which("lua5.1") or shutil.which("luajit")

MOCK = r"""
-- Minimal DCS API mock -------------------------------------------------------
local now = 0
local scheduled = {}
timer = {
  getTime = function() return now end,
  scheduleFunction = function(f, arg, t) table.insert(scheduled, {f = f, arg = arg, t = t}) end,
}
function run_timers(until_t)
  local again = true
  while again do
    again = false
    table.sort(scheduled, function(a, b) return a.t < b.t end)
    if scheduled[1] and scheduled[1].t <= until_t then
      local job = table.remove(scheduled, 1)
      now = job.t
      local nxt = job.f(job.arg, now)
      if nxt then table.insert(scheduled, {f = job.f, arg = job.arg, t = nxt}) end
      again = true
    end
  end
  now = until_t
end
env = {info = function() end, error = function(m) print("ENV ERROR " .. m) end}
messages = {}
trigger = {action = {outTextForGroup = function(gid, text) table.insert(messages, text) end}}
menus = {}
local menu_id = 0
missionCommands = {
  addSubMenuForGroup = function(gid, name, parent)
    menu_id = menu_id + 1
    menus[menu_id] = {name = name, parent = parent, children = {}}
    if parent then table.insert(menus[parent].children, menu_id) end
    return menu_id
  end,
  addCommandForGroup = function(gid, name, parent, fn, arg)
    menu_id = menu_id + 1
    menus[menu_id] = {name = name, parent = parent, fn = fn, arg = arg, children = {}}
    if parent then table.insert(menus[parent].children, menu_id) end
    return menu_id
  end,
  removeItemForGroup = function(gid, id) menus[id] = nil end,
}
function find_menu(path)
  local current = nil
  for _, part in ipairs(path) do
    local found = nil
    for id, m in pairs(menus) do
      if m.parent == current and string.find(m.name, part, 1, true) == 1 then found = id end
    end
    if not found then return nil end
    current = found
  end
  return menus[current]
end
world = {event = {S_EVENT_DEAD = 8, S_EVENT_BIRTH = 15, S_EVENT_LAND = 4,
  S_EVENT_TAKEOFF = 3, S_EVENT_RUNWAY_TAKEOFF = 54, S_EVENT_RUNWAY_TOUCH = 55}}
handlers = {}
world.addEventHandler = function(h) table.insert(handlers, h) end
land = {getHeight = function(p) return 0 end}
statics = {}
local function static_object(name)
  local o = statics[name]
  return {
    isExist = function() return statics[name] ~= nil end,
    getPoint = function() return {x = o.x, y = o.alt or 0, z = o.y} end,
    destroy = function() statics[name] = nil end,
  }
end
StaticObject = {getByName = function(name) if statics[name] then return static_object(name) end end}
coalition = {addStaticObject = function(country, data) statics[data.name] = data end}
heli = {fuel = 1.0, inAir = false, x = 1000, z = 2000}
local unit = {
  isExist = function() return true end,
  inAir = function() return heli.inAir end,
  getPoint = function() return {x = heli.x, y = 0, z = heli.z} end,
  getPosition = function() return {p = {x = heli.x, y = 0, z = heli.z}, x = {x = 1, y = 0, z = 0}} end,
  getFuel = function() return heli.fuel end,
  getCountry = function() return 2 end,
}
local group = {isExist = function() return true end, getID = function() return 7 end,
  getUnit = function() return unit end, getName = function() return "Uzi 7" end}
Group = {getByName = function(name) if name == "Uzi 7" then return group end end}
dirty_state = false
"""

DATA = r"""
dcsRetributionCargo = {
  flights = {["Uzi 7"] = {tid = "abcd1234", helicopter = true,
                          emptyKg = 2883, maxKg = 4310, fuelMaxKg = 631}},
  bases = {{id = "base-1", name = "Senaki", x = 1000, z = 2000, radius = 2500}},
  stock = {["base-1"] = {
    {clsid = "HELLFIRE", name = "AGM-114K Hellfire", category = "Missile", kg = 45.3, qty = 30},
    {clsid = "GBU12", name = "GBU-12", category = "Bomb", kg = 277, qty = 3},
  }},
  crates = {{name = "Cargo abcd1234 1/1: 20x AGM-114K", tid = "abcd1234",
             source = "base-1", contents = {{clsid = "HELLFIRE", count = 20}}}},
}
statics["Cargo abcd1234 1/1: 20x AGM-114K"] = {x = 1000, y = 2025}
"""

SCENARIO = r"""
run_timers(5)
assert(find_menu({"Cargo", "Order at Senaki", "Missile", "AGM-114K", "10  ("}), "menu built")

-- order 10 Hellfires: crate appears 25 m to the right, stock goes down
local cmd = find_menu({"Cargo", "Order at Senaki", "Missile", "AGM-114K", "10  ("})
cmd.fn(cmd.arg)
local ordered = "Cargo abcd1234 R1: 10x AGM-114K Hellfire"
assert(statics[ordered], "crate spawned: " .. tostring(messages[#messages]))
assert(statics[ordered].mass == 453, "mass " .. statics[ordered].mass)
assert(math.abs(statics[ordered].y - 2025) < 0.01, "25 m to the right")
assert(dcsRetributionCargo.stock["base-1"][1].qty == 20)

-- 4 GBU-12: only 3 in stock. 2 GBU-12 (554 kg) fit; cancel refunds them.
local gbu = find_menu({"Cargo", "Order at Senaki", "Bomb", "GBU-12", "4"})
gbu.fn(gbu.arg)
assert(string.find(messages[#messages], "Only 3", 1, true), messages[#messages])
gbu = find_menu({"Cargo", "Order at Senaki", "Bomb", "GBU-12", "2  ("})
gbu.fn(gbu.arg)
assert(string.find(messages[#messages], "Cargo abcd1234 R2", 1, true), messages[#messages])
cmd = find_menu({"Cargo", "Cancel last order"})
cmd.fn(cmd.arg)
assert(dcsRetributionCargo.stock["base-1"][2].qty == 3, "cancel refunds")
assert(statics["Cargo abcd1234 R2: 2x GBU-12"] == nil, "cancelled crate removed")

-- A lower max weight: 2 GBU-12 no longer fit at full fuel.
dcsRetributionCargo.flights["Uzi 7"].maxKg = 3600
gbu.fn(gbu.arg)
assert(string.find(messages[#messages], "Too heavy", 1, true), messages[#messages])

-- airborne: the menu is rebuilt without ordering
heli.inAir = true
for _, h in ipairs(handlers) do
  h:onEvent({id = world.event.S_EVENT_TAKEOFF, initiator = {getName = function() return "Uzi 7-1" end,
    getGroup = function() return Group.getByName("Uzi 7") end}})
end
run_timers(10)
assert(find_menu({"Cargo", "Land at a friendly base"}), "no ordering in the air")

-- the planned crate was destroyed
for _, h in ipairs(handlers) do
  h:onEvent({id = world.event.S_EVENT_DEAD,
    initiator = {getName = function() return "Cargo abcd1234 1/1: 20x AGM-114K" end}})
end
statics["Cargo abcd1234 1/1: 20x AGM-114K"] = nil

print(json:encode(retribution_cargo_state()))
"""


@pytest.mark.skipif(LUA is None, reason="no Lua 5.1 interpreter")
def test_cargo_menu_orders_and_reports(tmp_path: Path) -> None:
    program = tmp_path / "run.lua"
    program.write_text(
        MOCK
        + JSON_LIB.read_text(encoding="utf-8")
        + "\n"
        + SCRIPT.read_text(encoding="utf-8")
        + "\n"
        + DATA
        + SCENARIO,
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(LUA), str(program)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr + result.stdout
    crates = {c["name"]: c for c in json.loads(result.stdout.strip().splitlines()[-1])}
    planned = crates["Cargo abcd1234 1/1: 20x AGM-114K"]
    assert planned["destroyed"] and not planned["exists"] and not planned["requested"]
    ordered = crates["Cargo abcd1234 R1: 10x AGM-114K Hellfire"]
    assert ordered["requested"] and ordered["exists"] and ordered["source"] == "base-1"
    assert ordered["contents"] == [{"clsid": "HELLFIRE", "count": 10}]
    assert (ordered["x"], ordered["z"]) == pytest.approx((1000, 2025))
