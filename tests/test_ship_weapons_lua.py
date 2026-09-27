"""Ship rearming at sea (resources/plugins/ship_weapons), run in Lua 5.1 against
a mock of the DCS API.

Skipped when no lua5.1 interpreter is installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("resources/plugins/ship_weapons/ship_weapons.lua")
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
    local nxt = job.f(job.arg, now)
    if nxt then table.insert(scheduled, {f = job.f, arg = job.arg, t = nxt}) end
  end
  now = t
end
env = {info = function() end}
pilot_msgs, side_msgs, cargo_kg = {}, {}, {}
trigger = {action = {
  outTextForGroup = function(gid, text) table.insert(pilot_msgs, text) end,
  outTextForCoalition = function(side, text) table.insert(side_msgs, text) end,
  setUnitInternalCargo = function(name, kg) cargo_kg[name] = kg end,
}}
group_cmds = {}
missionCommands = {
  addSubMenuForCoalition = function() return {} end,
  addCommandForCoalition = function() end,
  addSubMenuForGroup = function() return {} end,
  addCommandForGroup = function(gid, name, parent, fn, arg)
    group_cmds[name] = function() fn(arg) end
  end,
}
coalition = {side = {RED = 1, BLUE = 2}}
world = {event = {S_EVENT_LAND = 4, S_EVENT_TAKEOFF = 3, S_EVENT_DEAD = 8,
  S_EVENT_CRASH = 5, S_EVENT_PILOT_DEAD = 9, S_EVENT_PLAYER_LEAVE_UNIT = 21,
  S_EVENT_BIRTH = 15, S_EVENT_PLAYER_ENTER_UNIT = 20}}
handlers = {}
world.addEventHandler = function(h) table.insert(handlers, h) end
function fire(ev) for _, h in ipairs(handlers) do h:onEvent(ev) end end
Airbase = {Category = {AIRDROME = 0, HELIPAD = 1, SHIP = 2}}

units, groups = {}, {}
Unit = {Category = {AIRPLANE = 0, HELICOPTER = 1, SHIP = 3}}
Unit.getByName = function(n) return units[n] end
Group = {Category = {SHIP = 3}}
Group.getByName = function(n) return groups[n] end

local function new_unit(name, side, cat, ammo, x)
  local u = {name = name, side = side, cat = cat, ammo = ammo, x = x or 0, z = 0,
             life = 100, life0 = 100, air = false, attrs = {}, alive = true}
  function u:getName() return self.name end
  function u:isExist() return self.alive end
  function u:getCoalition() return self.side end
  function u:getDesc() return {category = self.cat} end
  function u:getAmmo()
    if self.ammo <= 0 then return {} end  -- DCS drops empty weapons
    return {{count = self.ammo, desc = {typeName = "SM2", displayName = "SM-2"}}}
  end
  function u:getTypeName() return "USS_Arleigh_Burke_IIa" end
  function u:getLife() return self.life end
  function u:getLife0() return self.life0 end
  function u:hasAttribute(a) return self.attrs[a] == true end
  function u:inAir() return self.air end
  function u:getPoint() return {x = self.x, y = 0, z = self.z} end
  function u:getGroup() return self.group end
  units[name] = u
  return u
end

function make_ship_group(gname, side, ammo_list)
  local g = {name = gname, side = side, units = {}}
  function g:getName() return self.name end
  function g:isExist() return true end
  function g:getUnits() return self.units end
  function g:getCoalition() return self.side end
  function g:getID() return 1 end
  for i, a in ipairs(ammo_list) do
    local u = new_unit(gname .. "-" .. i, side, Unit.Category.SHIP, a, (i - 1) * 50)
    u.group = g
    table.insert(g.units, u)
  end
  groups[gname] = g
  return g
end

function make_heli(name, side)
  local g = {name = name .. "-group"}
  function g:getID() return 99 end
  function g:getName() return self.name end
  function g:isExist() return true end
  local h = new_unit(name, side, Unit.Category.HELICOPTER, 0, 10)
  function g:getUnits() return {h} end
  h.group = g
  groups[g.name] = nil  -- not a ship group
  heli_groups = heli_groups or {}
  heli_groups[g.name] = g
  function h:getPlayerName() return "Pilot" end
  return h
end
local _group_by_name = Group.getByName
Group.getByName = function(n) return (heli_groups and heli_groups[n]) or _group_by_name(n) end

function ship_place(u)
  return {getName = function() return u.name end,
          getDesc = function() return {category = Airbase.Category.SHIP} end}
end

coalition.getGroups = function(side, cat)
  local out = {}
  for _, g in pairs(groups) do if g.side == side then table.insert(out, g) end end
  table.sort(out, function(a, b) return a.name < b.name end)
  return out
end

respawns = {}
mist = {
  getCurrentGroupData = function(n)
    local g = groups[n]
    local d = {name = n, units = {}}
    for _, u in ipairs(g.units) do
      if u.alive then table.insert(d.units, {unitName = u.name, x = u.x, y = u.z, speed = 5}) end
    end
    return d
  end,
  getGroupRoute = function(n) return {{x = 0, y = 0}, {x = 10000, y = 0}, {x = 20000, y = 0}} end,
  dynAdd = function(d)
    table.insert(respawns, d)
    for _, ud in ipairs(d.units) do units[ud.unitName].ammo = FULL[ud.unitName] end
  end,
}
function enable_set_ammo()
  set_ammo_calls = {}
  trigger.action.setAmmo = function(name, ammo)
    table.insert(set_ammo_calls, name)
    units[name].ammo = ammo[1] and ammo[1].count or 0
  end
end

function land(heli, ship) fire({id = world.event.S_EVENT_LAND, initiator = heli, place = ship_place(ship)}) end
function takeoff(heli) heli.air = true; fire({id = world.event.S_EVENT_TAKEOFF, initiator = heli}) end
function check(cond, what) if not cond then error("FAILED: " .. what, 2) end end
function has_msg(list, pat)
  for _, m in ipairs(list) do if string.find(m, pat, 1, true) then return true end end
  return false
end
"""


def _run(scenario: str) -> str:
    assert LUA is not None
    code = MOCK + "\n" + SCRIPT.read_text() + "\n" + scenario + '\nprint("PASS")\n'
    result = subprocess.run(
        [LUA, "-"], input=code, capture_output=True, text=True, timeout=30
    )
    assert "PASS" in result.stdout, result.stdout + result.stderr
    return result.stdout


pytestmark = pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")

SETUP = r"""
FULL = {["Frigate-1"] = 100, ["Frigate-2"] = 100}
local g = make_ship_group("Frigate", coalition.side.BLUE, {100, 100})
local heli = make_heli("Seahawk", coalition.side.BLUE)
run_until(6)  -- init: full loads remembered
ship = units["Frigate-1"]
g.units[1].ammo = 40   -- fired: lowest weapon at 40% -> 3 loads needed
g.units[2].ammo = 100
"""


def test_two_loads_then_full_rearm_after_takeoff() -> None:
    _run(SETUP + r"""
g.units[1].ammo = 70  -- lowest weapon at 70%: 2 loads
land(heli, ship)
check(has_msg(pilot_msgs, "stay on the deck for 15 min"), "load started")
run_until(6 + 15 * 60 + 20)
check(has_msg(pilot_msgs, "load delivered (1/2)"), "first load")
check(#respawns == 0, "no respawn after one load")

-- Cooldown: a second landing straight away is refused.
takeoff(heli); heli.air = false
land(heli, ship)
check(has_msg(pilot_msgs, "next rearm load in"), "cooldown refusal")

-- After the 30 min cooldown the second load completes the rearm...
takeoff(heli); heli.air = false
run_until(6 + 15 * 60 + 20 + 30 * 60)
land(heli, ship)
run_until(timer.getTime() + 15 * 60 + 20)
check(has_msg(pilot_msgs, "final load delivered"), "final load")
-- ...but not while the helicopter is still on the deck.
run_until(timer.getTime() + 60)
check(#respawns == 0, "no respawn with a helicopter on the deck")
takeoff(heli)
run_until(timer.getTime() + 15)
check(#respawns == 1, "respawned once the deck is clear")
check(units["Frigate-1"].ammo == 100, "full ammo again")
check(has_msg(side_msgs, "Frigate is fully rearmed"), "coalition told")
check(retribution_respawning["Frigate-1"] ~= nil, "loss events suppressed")
""")


def test_leaving_the_deck_cancels_the_load() -> None:
    _run(SETUP + r"""
land(heli, ship)
run_until(6 + 5 * 60)
heli.x = 5000   -- flew off without a takeoff event
run_until(6 + 16 * 60)
check(has_msg(pilot_msgs, "Rearm load cancelled"), "cancelled")
check(ShipWeapons.groups["Frigate"].delivered == 0, "nothing delivered")
""")


def test_damaged_ship_is_not_rearmed() -> None:
    _run(SETUP + r"""
g.units[2].life = 60
land(heli, ship)
check(has_msg(pilot_msgs, "damaged - cannot rearm at sea"), "refused")
check(ShipWeapons.sessions["Seahawk"] == nil, "no session")
""")


def test_carrier_groups_are_never_respawned() -> None:
    _run(SETUP + r"""
g.units[1].attrs["AircraftCarrier"] = true
land(heli, ship)
check(has_msg(pilot_msgs, "Carrier groups cannot be rearmed at sea"), "refused")
""")


def test_enemy_ships_are_ignored() -> None:
    _run(SETUP + r"""
local red = make_heli("Hind", coalition.side.RED)
land(red, ship)
check(#pilot_msgs == 0, "no reaction to an enemy helicopter")
""")


def test_fully_armed_ship_needs_nothing() -> None:
    _run(SETUP + r"""
g.units[1].ammo = 100
land(heli, ship)
check(has_msg(pilot_msgs, "is fully loaded"), "nothing to do")
""")


def test_redfor_ships_rearm_on_their_own() -> None:
    _run(r"""
FULL = {["Moskva-1"] = 100}
local g = make_ship_group("Moskva", coalition.side.RED, {100})
run_until(6)
g.units[1].ammo = 15  -- below 25%: 5 loads needed
run_until(6 + 30 * 60 * 5 + 30)
check(#respawns == 1, "rearmed after 5 loads")
check(units["Moskva-1"].ammo == 100, "full again")
""")


def test_remaining_route_starts_after_the_current_leg() -> None:
    _run(r"""
local pts = {{x = 0, y = 0}, {x = 10000, y = 0}, {x = 20000, y = 0}, {x = 30000, y = 0}}
local rest = ShipWeapons.remainingRoute(pts, {x = 12000, y = 300})
check(#rest == 2 and rest[1].x == 20000, "skips passed waypoints")
check(#ShipWeapons.remainingRoute({{x = 0, y = 0}}, {x = 5, y = 5}) == 0, "stationary")
""")


def test_set_ammo_adds_twenty_percent_per_load_without_respawn() -> None:
    _run(
        r"""
enable_set_ammo()
"""
        + SETUP
        + r"""
g.units[1].ammo = 0   -- SM-2 empty: 5 loads needed
land(heli, ship)
run_until(6 + 15 * 60 + 20)
check(units["Frigate-1"].ammo == 20, "+20% of 100")
check(units["Frigate-2"].ammo == 100, "capped at full")
check(#respawns == 0, "no respawn when DCS can set ammo")
check(has_msg(pilot_msgs, "4 more load(s) to full"), "progress")
"""
    )


def test_status_shows_each_weapon_and_the_rearm_state() -> None:
    _run(SETUP + r"""
local text = ShipWeapons.statusText("Frigate-1")
check(string.find(text, "=== Frigate-1 - Weapons Status ===", 1, true), "title")
check(string.find(text, "SM-2", 1, true) and string.find(text, "40 / 100", 1, true), "weapon row")
check(string.find(text, "[####------] 40%", 1, true), "load bar")
check(string.find(text, "Rearm: loads 0/3 delivered - READY", 1, true), "rearm line")
g.units[1].ammo = 0
text = ShipWeapons.statusText("Frigate-1")
check(string.find(text, "0 / 100", 1, true), "empty weapon still listed")
""")


CRATES = r"""
dcsRetributionNaval = {crateKg = 500, bases = {
  {id = "base-1", name = "Hatzor", x = 50000, z = 0, radius = 2500, crates = 1},
}}
"""


def _crate_setup(extra: str = "") -> str:
    return CRATES + SETUP + r"""
fire({id = world.event.S_EVENT_BIRTH, initiator = heli})
function at_base() heli.x = 50000; heli.z = 0; heli.air = false end
function at_ship() heli.x = 10; heli.z = 0; heli.air = false end
""" + extra


def test_crate_needed_to_rearm_when_crates_are_in_use() -> None:
    _run(_crate_setup() + r"""
at_ship()
land(heli, ship)
check(has_msg(pilot_msgs, "Bring a naval munitions crate"), "crate required")
check(ShipWeapons.sessions["Seahawk"] == nil, "no unload without a crate")
""")


def test_crate_loaded_at_base_is_used_up_on_the_ship() -> None:
    _run(_crate_setup() + r"""
at_base()
group_cmds["Load crate (500 kg)"]()
check(has_msg(pilot_msgs, "crate loaded at Hatzor"), "loaded")
check(cargo_kg["Seahawk"] == 500, "real weight")
group_cmds["Load crate (500 kg)"]()
check(has_msg(pilot_msgs, "already carry"), "one crate at a time")

at_ship()
land(heli, ship)
check(has_msg(pilot_msgs, "stay on the deck for 15 min to unload the crate"), "unloading")
run_until(timer.getTime() + 15 * 60 + 20)
check(has_msg(pilot_msgs, "load delivered (1/3)"), "load counted")
check(cargo_kg["Seahawk"] == 0, "crate gone")
check(ShipWeapons.cargo["Seahawk"] == nil, "nothing aboard")

local state = retribution_naval_state()
check(#state == 1 and state[1].loaded == 1 and state[1].delivered == 1, "reported")
check(state[1].base == "base-1", "charged to the pickup base")
""")


def test_base_runs_out_of_crates_and_returned_crates_go_back() -> None:
    _run(_crate_setup() + r"""
at_base()
group_cmds["Load crate (500 kg)"]()
group_cmds["Return crate to base"]()
check(has_msg(pilot_msgs, "returned to Hatzor"), "returned")
check(cargo_kg["Seahawk"] == 0, "weight removed")
check(retribution_naval_state()[1].loaded == 0, "not charged")
group_cmds["Load crate (500 kg)"]()   -- the only crate again
local other = make_heli("Knighthawk", coalition.side.BLUE)
other.x = 50000
ShipWeapons.menus[99] = nil
fire({id = world.event.S_EVENT_BIRTH, initiator = other})
group_cmds["Load crate (500 kg)"]()
check(has_msg(pilot_msgs, "no ammunition left"), "base empty")
""")


def test_crate_is_lost_with_the_helicopter() -> None:
    _run(_crate_setup() + r"""
at_base()
group_cmds["Load crate (500 kg)"]()
fire({id = world.event.S_EVENT_CRASH, initiator = heli})
check(ShipWeapons.cargo["Seahawk"] == nil, "crate lost")
local state = retribution_naval_state()
check(state[1].loaded == 1 and state[1].delivered == 0, "charged, not delivered")
""")


def test_no_crate_needed_outside_retribution() -> None:
    _run(SETUP + r"""
land(heli, ship)
check(has_msg(pilot_msgs, "stay on the deck"), "old behaviour without crate data")
""")
