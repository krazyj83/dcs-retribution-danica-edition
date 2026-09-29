-- =============================================================================
-- ship_weapons.lua  -  DCS Retribution: ship weapons status and rearming at sea
-- =============================================================================
-- F10 > Ship Weapons > <ship> > Ammo Status shows each weapon's rounds left,
-- a load bar and the rearm state.
--
-- A helicopter loads a naval munitions crate at a friendly base (F10 >
-- Naval munitions; real weight, charged to the base's ammunition stock),
-- lands on a friendly ship and stays on the deck for CFG.load_time (15 min):
-- that delivers one rearm load, 20% of every weapon's full load. A ship group
-- accepts one load per CFG.cooldown (30 min). Missions generated without crate
-- data (dcsRetributionNaval) accept a 15-min stay without a crate.
--
-- How a load reaches the ship depends on the DCS version:
--   * If DCS offers trigger.action.setAmmo, the load is added straight away
--     (+20% on every weapon, capped at full).
--   * Otherwise DCS scripts can read ammo but not add it, and the only way to
--     give it back is to respawn the ship, which gives a full load. Loads are
--     then counted, and once enough have been delivered to refill the most
--     depleted weapon, the group is respawned in place (same names, position,
--     heading and remaining route) fully armed, as soon as no helicopter is
--     standing on any of its decks.
-- The mode in use is written to dcs.log at mission start.
--
--   * Damaged ships are not rearmed (a respawn would repair them for free).
--   * Groups with an aircraft carrier or LHA are not rearmed at sea (a respawn
--     would destroy the aircraft on their decks).
--   * Ammo does not carry over to the next mission: DCS starts every ship full.
--   * REDFOR ships rearm on their own (option "REDFOR ships rearm
--     automatically"): a group with a weapon below CFG.redfor_threshold gets
--     one load per cooldown until it is full.
--
-- Needs MIST (loaded by the base plugin).
-- =============================================================================

local CFG = {
    load_time         = 15 * 60,  -- seconds on the deck for one load
    load_fraction     = 0.20,     -- one load = 20% of each weapon's full load
    cooldown          = 30 * 60,  -- seconds between loads for one group
    max_deck_distance = 150,      -- metres from the ship's centre
    poll              = 15,       -- seconds between deck checks
    respawn_check     = 10,       -- seconds between pending-respawn checks
    redfor_interval   = 30 * 60,  -- one REDFOR load per cooldown
    redfor_threshold  = 0.25,
}

-- The plugin options are set after this script loads (luaplugin.py injects a
-- plugin's configuration after its scripts), so read them in init().
local function redforAutoRearm()
    local p = dcsRetribution and dcsRetribution.plugins
        and dcsRetribution.plugins.ship_weapons
    if p and p.redforAutoRearm ~= nil then
        return p.redforAutoRearm
    end
    return true
end

ShipWeapons = {
    CFG = CFG,
    full = {},        -- [unitName] = {order = {key...}, [key] = {name, count, desc}}
    groups = {},      -- [groupName] = {delivered, lastLoad, pending}
    landed = {},      -- [heliName] = shipName
    sessions = {},    -- [heliName] = {ship, group, started}
}
local SW = ShipWeapons

local function log(msg)
    env.info("DCSRetribution|Ship weapons: " .. msg)
end

--- True when this DCS can add ammo to a unit directly.
function SW.canSetAmmo()
    return trigger and trigger.action and type(trigger.action.setAmmo) == "function"
end

-- ── Ammo bookkeeping ────────────────────────────────────────────────────────
-- Weapons are matched by type name: DCS returns new desc tables on every
-- getAmmo() call, and drops a weapon from the list when it reaches zero.

local function slotKey(slot)
    local d = slot.desc or {}
    return d.typeName or d.displayName or "?"
end

local function slotName(slot)
    local d = slot.desc or {}
    return d.displayName or d.typeName or "Unknown weapon"
end

local function currentCounts(unit)
    local counts = {}
    for _, slot in ipairs(unit:getAmmo() or {}) do
        local k = slotKey(slot)
        counts[k] = (counts[k] or 0) + (slot.count or 0)
    end
    return counts
end

--- Remember the most of each weapon a unit has been seen with: its full load.
local function noteFull(unit)
    local name = unit:getName()
    local full = SW.full[name]
    if not full then
        full = {order = {}}
        SW.full[name] = full
    end
    local seen = {}
    for _, slot in ipairs(unit:getAmmo() or {}) do
        local k = slotKey(slot)
        seen[k] = (seen[k] or 0) + (slot.count or 0)
        if not full[k] then
            full[k] = {name = slotName(slot), count = 0, desc = slot.desc}
            full.order[#full.order + 1] = k
        end
    end
    for k, n in pairs(seen) do
        if n > full[k].count then
            full[k].count = n
        end
    end
    return full
end

--- Fractions of full for one unit: mean over its weapons, and the lowest.
local function unitFractions(unit)
    local full = noteFull(unit)
    local cur = currentCounts(unit)
    local sum, n, low = 0, 0, 1
    for _, k in ipairs(full.order) do
        if full[k].count > 0 then
            local f = math.min(1, (cur[k] or 0) / full[k].count)
            sum, n = sum + f, n + 1
            if f < low then low = f end
        end
    end
    if n == 0 then return nil, nil end
    return sum / n, low
end

local function aliveUnits(group)
    local units = {}
    if group and group:isExist() then
        for _, u in ipairs(group:getUnits() or {}) do
            if u and u:isExist() then
                units[#units + 1] = u
            end
        end
    end
    return units
end

--- Group ammo: mean fraction over all weapons, and the most depleted weapon.
--- nil if the group has no weapons.
function SW.ratio(group)
    local sum, n, low = 0, 0, 1
    for _, u in ipairs(aliveUnits(group)) do
        local mean, l = unitFractions(u)
        if mean then
            sum, n = sum + mean, n + 1
            if l < low then low = l end
        end
    end
    if n == 0 then return nil, nil end
    return sum / n, low
end

--- Loads needed to refill the most depleted weapon.
function SW.loadsNeeded(lowest)
    if lowest == nil or lowest >= 0.999 then return 0 end
    return math.ceil((1 - lowest) / CFG.load_fraction - 1e-6)
end

local function isDamaged(group)
    for _, u in ipairs(aliveUnits(group)) do
        local life0 = u:getLife0()
        if life0 and life0 > 0 and u:getLife() < life0 then
            return true
        end
    end
    return false
end

local function isCarrierGroup(group)
    for _, u in ipairs(aliveUnits(group)) do
        if u:hasAttribute("AircraftCarrier") or u:hasAttribute("Aircraft Carriers") then
            return true
        end
    end
    return false
end

local function state(groupName)
    local s = SW.groups[groupName]
    if not s then
        s = {delivered = 0, lastLoad = nil, pending = false}
        SW.groups[groupName] = s
    end
    return s
end

local function cooldownLeft(s)
    if not s.lastLoad then return 0 end
    return math.max(0, CFG.cooldown - (timer.getTime() - s.lastLoad))
end

local function minutes(seconds)
    return math.ceil(seconds / 60)
end

local function pct(f)
    return math.floor((f or 1) * 100 + 0.5)
end

-- ── Respawn in place (when DCS cannot add ammo) ─────────────────────────────

local function dist2(a, b)
    local dx, dy = a.x - b.x, a.y - b.y
    return dx * dx + dy * dy
end

--- Waypoints still ahead of pos: the ones after the closest route leg.
function SW.remainingRoute(points, pos)
    if not points or #points < 2 then return {} end
    local best, bestD = 1, math.huge
    for i = 1, #points - 1 do
        local a, b = points[i], points[i + 1]
        local abx, aby = b.x - a.x, b.y - a.y
        local len2 = abx * abx + aby * aby
        local t = 0
        if len2 > 0 then
            t = math.max(0, math.min(1, ((pos.x - a.x) * abx + (pos.y - a.y) * aby) / len2))
        end
        local d = dist2(pos, {x = a.x + t * abx, y = a.y + t * aby})
        if d < bestD then
            best, bestD = i, d
        end
    end
    local rest = {}
    for i = best + 1, #points do
        rest[#rest + 1] = points[i]
    end
    return rest
end

function SW.respawn(groupName)
    local group = Group.getByName(groupName)
    if not group or not group:isExist() then return false end
    local data = mist.getCurrentGroupData(groupName)
    if not data or not data.units or #data.units == 0 then return false end

    local lead = data.units[1]
    local here = {x = lead.x, y = lead.y}
    local route = mist.getGroupRoute(groupName, true) or {}
    local ahead = SW.remainingRoute(route, here)
    local speed = (ahead[1] and ahead[1].speed) or lead.speed or 0
    local points = {{
        x = here.x, y = here.y, alt = 0, type = "Turning Point",
        action = "Turning Point", speed = speed, task = {id = "ComboTask", params = {tasks = {}}},
    }}
    for _, p in ipairs(ahead) do
        points[#points + 1] = p
    end
    data.route = {points = points}
    data.clone = nil

    -- Replacing the group removes the old units. Tell dcs_retribution.lua
    -- not to count them as lost.
    retribution_respawning = retribution_respawning or {}
    for _, u in ipairs(data.units) do
        retribution_respawning[u.unitName or u.name] = timer.getTime() + 10
    end

    local ok, err = pcall(mist.dynAdd, data)
    if not ok then
        log("respawn of " .. groupName .. " failed: " .. tostring(err))
        return false
    end
    log("rearmed " .. groupName .. " (respawned in place)")
    return true
end

local function deckClear(groupName)
    for heli, ship in pairs(SW.landed) do
        local h = Unit.getByName(heli)
        local s = Unit.getByName(ship)
        if h and h:isExist() and s and s:isExist() and s:getGroup():getName() == groupName then
            return false
        end
    end
    return true
end

local function finishRearm(groupName)
    local group = Group.getByName(groupName)
    local s = state(groupName)
    if not group or not group:isExist() then
        SW.groups[groupName] = nil
        return
    end
    if isDamaged(group) then
        if not s.damageWarned then
            trigger.action.outTextForCoalition(group:getCoalition(),
                "[Ship Weapons] " .. groupName .. " was damaged before rearming finished - rearm on hold.", 15)
            s.damageWarned = true
        end
        return
    end
    if not deckClear(groupName) then return end
    local side = group:getCoalition()
    if SW.respawn(groupName) then
        SW.groups[groupName] = {delivered = 0, lastLoad = s.lastLoad, pending = false}
        trigger.action.outTextForCoalition(side, "[Ship Weapons] " .. groupName .. " is fully rearmed.", 15)
    end
end

local function checkPending(_, time)
    for groupName, s in pairs(SW.groups) do
        if s.pending then
            finishRearm(groupName)
        end
    end
    return time + CFG.respawn_check
end

-- ── Delivering a load ───────────────────────────────────────────────────────

--- +20% of every weapon's full load on one unit, capped at full.
local function topUp(unit)
    local full = noteFull(unit)
    local cur = currentCounts(unit)
    local ammo = {}
    for _, k in ipairs(full.order) do
        local f = full[k]
        if f.count > 0 then
            local add = math.max(1, math.floor(f.count * CFG.load_fraction))
            ammo[#ammo + 1] = {desc = f.desc, count = math.min((cur[k] or 0) + add, f.count)}
        end
    end
    trigger.action.setAmmo(unit:getName(), ammo)
end

--- One load delivered to a group. Returns a message for the pilot.
function SW.deliverLoad(groupName)
    local group = Group.getByName(groupName)
    local s = state(groupName)
    s.lastLoad = timer.getTime()

    if SW.canSetAmmo() then
        for _, u in ipairs(aliveUnits(group)) do
            topUp(u)
        end
        local mean, low = SW.ratio(group)
        local left = SW.loadsNeeded(low)
        if left == 0 then
            return string.format("[Ship Weapons] %s: load delivered - fully loaded (%d%%).", groupName, pct(mean))
        end
        return string.format("[Ship Weapons] %s: load delivered - now %d%%, %d more load(s) to full. Next load in %d min.",
            groupName, pct(mean), left, minutes(CFG.cooldown))
    end

    s.delivered = s.delivered + 1
    local _, low = SW.ratio(group)
    local needed = SW.loadsNeeded(low)
    if s.delivered >= needed then
        s.pending = true
        s.damageWarned = false
        return "[Ship Weapons] " .. groupName .. ": final load delivered - the ship rearms fully once the deck is clear."
    end
    return string.format("[Ship Weapons] %s: load delivered (%d/%d). Next load in %d min.",
        groupName, s.delivered, needed, minutes(CFG.cooldown))
end

--- Why this ship group can't take a load now, or nil if it can.
function SW.refusal(groupName, group)
    local s = state(groupName)
    if isCarrierGroup(group) then
        return "Carrier groups cannot be rearmed at sea."
    end
    local mean, low = SW.ratio(group)
    if mean == nil then
        return groupName .. " has no weapons to rearm."
    end
    if isDamaged(group) then
        return groupName .. " is damaged - cannot rearm at sea."
    end
    if s.pending then
        return groupName .. " has all its loads - it rearms once the deck is clear."
    end
    if SW.loadsNeeded(low) == 0 then
        return groupName .. " is fully loaded."
    end
    local cd = cooldownLeft(s)
    if cd > 0 then
        return string.format("%s: next rearm load in %d min.", groupName, minutes(cd))
    end
    return nil
end

--- The "Rearm:" line of the status display.
local function rearmLine(groupName, group)
    local s = state(groupName)
    if isCarrierGroup(group) then
        return "Rearm: not possible at sea (carrier group)"
    end
    if isDamaged(group) then
        return "Rearm: DAMAGED - not possible at sea"
    end
    if s.pending then
        return "Rearm: all loads delivered - completes when the deck is clear"
    end
    local _, low = SW.ratio(group)
    local needed = SW.loadsNeeded(low)
    local cd = cooldownLeft(s)
    local text
    if needed == 0 then
        text = "Rearm: not needed"
    elseif SW.canSetAmmo() then
        text = string.format("Rearm: %d helicopter load(s) to full", needed)
    else
        text = string.format("Rearm: loads %d/%d delivered", math.min(s.delivered, needed), needed)
    end
    if cd > 0 then
        local m, sec = math.floor(cd / 60), math.ceil(cd % 60)
        return text .. string.format(" - next load in %d m %02d s", m, sec)
    end
    if needed > 0 then
        return text .. string.format(" - READY (%d min on deck per load)", minutes(CFG.load_time))
    end
    return text
end

-- ── Naval munitions crates ──────────────────────────────────────────────────
-- dcsRetributionNaval (written by Retribution): {crateKg, bases = {{id, name,
-- x, z, radius, crates}}}. A helicopter loads one crate at a friendly base
-- (F10 > Naval munitions); it adds real weight (internal cargo) and is used
-- up by a 15-min stay on a ship's deck. Retribution charges each base's
-- ammunition stock for the crates it handed out (retribution_naval_state).

SW.cargo = {}        -- [heliName] = {base = id, name = baseName}
SW.crates = {}       -- [baseId] = crates left at that base this mission
SW.report = {}       -- [baseId] = {name, loaded, delivered}
SW.menus = {}        -- [groupId] = true once the menu is built

local function navalData()
    return dcsRetributionNaval
end

--- True when this mission uses naval munitions crates.
function SW.cratesInUse()
    return navalData() ~= nil
end

local function crateKg()
    return (navalData() and navalData().crateKg) or 500
end

local function baseAt(point)
    local best, bestD = nil, nil
    for _, base in ipairs((navalData() or {}).bases or {}) do
        local dx, dz = point.x - base.x, point.z - base.z
        local d = math.sqrt(dx * dx + dz * dz)
        if d <= base.radius and (bestD == nil or d < bestD) then
            best, bestD = base, d
        end
    end
    return best
end

local function cratesLeft(base)
    if SW.crates[base.id] == nil then
        SW.crates[base.id] = base.crates or 0
    end
    return SW.crates[base.id]
end

local function reportFor(base)
    local r = SW.report[base.id]
    if not r then
        r = {name = base.name, loaded = 0, delivered = 0}
        SW.report[base.id] = r
    end
    return r
end

local function setWeight(heli, kg)
    pcall(trigger.action.setUnitInternalCargo, heli:getName(), kg)
end

function retribution_naval_state()
    local out = {}
    for id, r in pairs(SW.report) do
        out[#out + 1] = {base = id, name = r.name, loaded = r.loaded, delivered = r.delivered}
    end
    return out
end

local function groupMessage(groupId, text)
    trigger.action.outTextForGroup(groupId, "[Ship Weapons] " .. text, 15)
end

local function leadHeli(groupName)
    local g = Group.getByName(groupName)
    if not g or not g:isExist() then return nil end
    return g:getUnits()[1]
end

function SW.loadCrate(groupName)
    local heli = leadHeli(groupName)
    if not heli then return end
    local gid = heli:getGroup():getID()
    local name = heli:getName()
    if SW.cargo[name] then
        return groupMessage(gid, "You already carry a naval munitions crate from " .. SW.cargo[name].name .. ".")
    end
    if heli:inAir() then
        return groupMessage(gid, "Land at a friendly base to load a naval munitions crate.")
    end
    local base = baseAt(heli:getPoint())
    if not base then
        return groupMessage(gid, "No friendly base here - naval munitions are loaded at friendly bases.")
    end
    if cratesLeft(base) <= 0 then
        return groupMessage(gid, base.name .. " has no ammunition left for naval munitions crates.")
    end
    SW.crates[base.id] = cratesLeft(base) - 1
    reportFor(base).loaded = reportFor(base).loaded + 1
    SW.cargo[name] = {base = base.id, name = base.name}
    setWeight(heli, crateKg())
    groupMessage(gid, string.format(
        "Naval munitions crate loaded at %s (%d kg, %d left). Land on a friendly ship and stay %d min on the deck.",
        base.name, crateKg(), SW.crates[base.id], minutes(CFG.load_time)))
end

function SW.returnCrate(groupName)
    local heli = leadHeli(groupName)
    if not heli then return end
    local gid = heli:getGroup():getID()
    local cargo = SW.cargo[heli:getName()]
    if not cargo then
        return groupMessage(gid, "You carry no naval munitions crate.")
    end
    local base = (not heli:inAir()) and baseAt(heli:getPoint()) or nil
    if not base or base.id ~= cargo.base then
        return groupMessage(gid, "Land at " .. cargo.name .. " to return the crate.")
    end
    SW.crates[base.id] = cratesLeft(base) + 1
    reportFor(base).loaded = reportFor(base).loaded - 1
    SW.cargo[heli:getName()] = nil
    setWeight(heli, 0)
    groupMessage(gid, "Naval munitions crate returned to " .. base.name .. ".")
end

function SW.crateStatus(groupName)
    local heli = leadHeli(groupName)
    if not heli then return end
    local gid = heli:getGroup():getID()
    local cargo = SW.cargo[heli:getName()]
    local lines = {}
    lines[#lines + 1] = cargo and ("Aboard: 1 naval munitions crate from " .. cargo.name)
        or "Aboard: no naval munitions crate"
    local base = baseAt(heli:getPoint())
    if base then
        lines[#lines + 1] = string.format("%s: %d crate(s) available", base.name, cratesLeft(base))
    end
    groupMessage(gid, table.concat(lines, "\n"))
end

--- Crate delivered: the helicopter is empty again.
local function crateUsed(heli)
    local cargo = SW.cargo[heli:getName()]
    if not cargo then return end
    local r = SW.report[cargo.base]
    if r then r.delivered = r.delivered + 1 end
    SW.cargo[heli:getName()] = nil
    setWeight(heli, 0)
end

function SW.addCrateMenu(unit)
    if not SW.cratesInUse() then return end
    local group = unit:getGroup()
    if not group then return end
    local gid = group:getID()
    if SW.menus[gid] then return end
    SW.menus[gid] = true
    local gname = group:getName()
    local menu = missionCommands.addSubMenuForGroup(gid, "Naval munitions")
    missionCommands.addCommandForGroup(gid, string.format("Load crate (%d kg)", crateKg()), menu, SW.loadCrate, gname)
    missionCommands.addCommandForGroup(gid, "Return crate to base", menu, SW.returnCrate, gname)
    missionCommands.addCommandForGroup(gid, "Crate status", menu, SW.crateStatus, gname)
end

-- ── Helicopter loads ────────────────────────────────────────────────────────

local function toPilot(heli, text)
    local g = heli:getGroup()
    if g then
        trigger.action.outTextForGroup(g:getID(), text, 15)
    end
end

local function endSession(heliName)
    SW.sessions[heliName] = nil
end

local function pollSession(heliName, time)
    local session = SW.sessions[heliName]
    if not session then return nil end
    local heli = Unit.getByName(heliName)
    local ship = Unit.getByName(session.ship)
    if not heli or not heli:isExist() or not ship or not ship:isExist() then
        endSession(heliName)
        return nil
    end
    local hp, sp = heli:getPoint(), ship:getPoint()
    local dx, dz = hp.x - sp.x, hp.z - sp.z
    if heli:inAir() or dx * dx + dz * dz > CFG.max_deck_distance ^ 2 then
        toPilot(heli, "[Ship Weapons] Rearm load cancelled - you left the deck of " .. session.ship .. ".")
        endSession(heliName)
        return nil
    end
    if timer.getTime() - session.started < CFG.load_time then
        return time + CFG.poll
    end
    endSession(heliName)
    local group = ship:getGroup()
    local why = SW.refusal(session.group, group)
    if why then
        toPilot(heli, "[Ship Weapons] Rearm load not delivered: " .. why)
        return nil
    end
    crateUsed(heli)
    toPilot(heli, SW.deliverLoad(session.group))
    return nil
end

function SW.onLanding(heli, place)
    local shipName = place:getName()
    local ship = Unit.getByName(shipName)
    if not ship or not ship:isExist() then return end
    if ship:getCoalition() ~= heli:getCoalition() then return end
    local heliName = heli:getName()
    SW.landed[heliName] = shipName
    local group = ship:getGroup()
    local groupName = group:getName()
    local why = SW.refusal(groupName, group)
    if why then
        toPilot(heli, "[Ship Weapons] " .. why)
        return
    end
    if SW.cratesInUse() and not SW.cargo[heliName] then
        toPilot(heli, "[Ship Weapons] Bring a naval munitions crate to rearm " .. groupName
            .. ": load one at a friendly base (F10 > Naval munitions).")
        return
    end
    SW.sessions[heliName] = {ship = shipName, group = groupName, started = timer.getTime()}
    local mean = SW.ratio(group)
    toPilot(heli, string.format(
        "[Ship Weapons] Rearming %s (%d%%): stay on the deck for %d min to unload the crate.",
        groupName, pct(mean), minutes(CFG.load_time)))
    timer.scheduleFunction(pollSession, heliName, timer.getTime() + CFG.poll)
end

local handler = {}
function handler:onEvent(event)
    local ok, err = pcall(function()
        local unit = event.initiator
        if not unit or not unit.getName then return end
        if event.id == world.event.S_EVENT_LAND then
            if not event.place or not event.place.getDesc then return end
            local desc = unit:getDesc()
            if not desc or desc.category ~= Unit.Category.HELICOPTER then return end
            local placeDesc = event.place:getDesc()
            if not placeDesc or placeDesc.category ~= Airbase.Category.SHIP then return end
            SW.onLanding(unit, event.place)
        elseif event.id == world.event.S_EVENT_BIRTH
            or event.id == world.event.S_EVENT_PLAYER_ENTER_UNIT then
            local desc = unit.getDesc and unit:getDesc()
            if desc and desc.category == Unit.Category.HELICOPTER
                and unit.getPlayerName and unit:getPlayerName()
                and unit:getCoalition() == coalition.side.BLUE then
                SW.addCrateMenu(unit)
            end
        elseif event.id == world.event.S_EVENT_TAKEOFF
            or event.id == world.event.S_EVENT_DEAD
            or event.id == world.event.S_EVENT_CRASH
            or event.id == world.event.S_EVENT_PILOT_DEAD
            or event.id == world.event.S_EVENT_PLAYER_LEAVE_UNIT then
            local name = unit:getName()
            SW.landed[name] = nil
            if event.id ~= world.event.S_EVENT_TAKEOFF then
                SW.cargo[name] = nil  -- crate lost with the helicopter
            end
            if SW.sessions[name] and event.id == world.event.S_EVENT_TAKEOFF then
                toPilot(unit, "[Ship Weapons] Rearm load cancelled - you took off.")
            end
            SW.sessions[name] = nil
        end
    end)
    if not ok then
        log("event error: " .. tostring(err))
    end
end

-- ── REDFOR logistics ────────────────────────────────────────────────────────

local function shipGroups(side)
    return coalition.getGroups(side, Group.Category.SHIP) or {}
end

local function redforRearm(_, time)
    for _, group in ipairs(shipGroups(coalition.side.RED)) do
        local groupName = group:getName()
        local mean, low = SW.ratio(group)
        local s = state(groupName)
        local started = s.delivered > 0 or (s.lastLoad ~= nil and SW.loadsNeeded(low) > 0)
        if mean and not s.pending and (started or low < CFG.redfor_threshold)
            and SW.refusal(groupName, group) == nil then
            SW.deliverLoad(groupName)
        end
    end
    return time + CFG.redfor_interval
end

-- ── F10 status ──────────────────────────────────────────────────────────────

--- The weapons status of one ship, for the F10 menu.
function SW.statusText(unitName)
    local unit = Unit.getByName(unitName)
    if not unit or not unit:isExist() then
        return "[Ship Weapons] " .. unitName .. " - not found or destroyed."
    end
    local group = unit:getGroup()
    local full = noteFull(unit)
    local cur = currentCounts(unit)
    local lines = {"=== " .. unitName .. " - Weapons Status ==="}
    local any = false
    for _, k in ipairs(full.order) do
        local f = full[k]
        if f.count > 0 then
            lines[#lines + 1] = string.format("  %-28s %d / %d", f.name, cur[k] or 0, f.count)
            any = true
        end
    end
    if not any then
        lines[#lines + 1] = "  (no weapons)"
        return table.concat(lines, "\n")
    end
    local mean, low = unitFractions(unit)
    local filled = math.floor(pct(mean) / 10)
    lines[#lines + 1] = ""
    lines[#lines + 1] = string.format("  Load:  [%s%s] %d%%", string.rep("#", filled), string.rep("-", 10 - filled), pct(mean))
    if SW.loadsNeeded(low) == 0 then
        lines[#lines + 1] = "  Status: FULLY LOADED"
    else
        lines[#lines + 1] = string.format("  Status: lowest weapon at %d%%", pct(low))
    end
    lines[#lines + 1] = "  " .. rearmLine(group:getName(), group)
    return table.concat(lines, "\n")
end

local function showStatus(args)
    trigger.action.outTextForCoalition(args.side, SW.statusText(args.unit), 25)
end

local function buildMenu(side)
    local root = missionCommands.addSubMenuForCoalition(side, "Ship Weapons")
    local count = 0
    for _, group in ipairs(shipGroups(side)) do
        for _, u in ipairs(aliveUnits(group)) do
            local mean = unitFractions(u)
            if mean then
                local uName, gName = u:getName(), group:getName()
                local label = gName ~= uName and (gName .. " / " .. uName) or uName
                local menu = missionCommands.addSubMenuForCoalition(side, label, root)
                missionCommands.addCommandForCoalition(side, "Ammo Status", menu, showStatus,
                    {side = side, unit = uName})
                count = count + 1
            end
        end
    end
    if count == 0 then
        missionCommands.addCommandForCoalition(side, "(no armed ships)", root, function() end)
    end
end

local function init()
    for _, side in ipairs({coalition.side.BLUE, coalition.side.RED}) do
        for _, group in ipairs(shipGroups(side)) do
            SW.ratio(group) -- remember the full loads
        end
        buildMenu(side)
    end
    world.addEventHandler(handler)
    timer.scheduleFunction(checkPending, nil, timer.getTime() + CFG.respawn_check)
    if redforAutoRearm() then
        timer.scheduleFunction(redforRearm, nil, timer.getTime() + CFG.redfor_interval)
    end
    log("ready - rearm mode: " .. (SW.canSetAmmo() and "setAmmo (+20% per load)" or "respawn when all loads are delivered"))
end

timer.scheduleFunction(function()
    local ok, err = pcall(init)
    if not ok then
        log("init failed: " .. tostring(err))
    end
end, nil, timer.getTime() + 5)
