-- =============================================================================
-- ship_weapons.lua  –  DCS Retribution Ship Weapons Management Plugin
-- =============================================================================
-- Part of the ship_weapons plugin.  Drop the whole folder into:
--   <Retribution repo>\resources\plugins\ship_weapons\
-- Then add "ship_weapons" to resources\plugins\plugins.json.
--
-- Settings exposed in the Retribution UI (via plugin.json):
--   • Enable / disable the plugin entirely          (main plugin checkbox)
--   • Persist ammo depletion across turns           (persistentDepletion)
--
-- These are injected by Retribution before this script runs as:
--   dcsRetribution.plugins.ship_weapons.persistentDepletion  (bool)
--
-- PERSISTENCE
--   When enabled, ship ammo ratios are saved to:
--     <DCS Saved Games>\Scripts\RetributionShipWeapons.lua
--   On the next mission start the script reads that file and reduces each
--   ship's starting ammo to match where the last mission left off.
--   The file is written every CFG.state_save_interval seconds AND on the
--   S_EVENT_MISSION_END event as a belt-and-suspenders approach.
-- =============================================================================


-- ──────────────────────────────────────────────────────────────────────────────
-- PLUGIN SETTINGS  –  read values injected by Retribution
-- ──────────────────────────────────────────────────────────────────────────────
-- Retribution injects these before this script runs; we default to true so
-- the feature is active even if the dcsRetribution global isn't present
-- (e.g. when testing in a standalone mission outside Retribution).

local PERSISTENT_DEPLETION = true

if dcsRetribution
   and dcsRetribution.plugins
   and dcsRetribution.plugins.ship_weapons then
    local p = dcsRetribution.plugins.ship_weapons
    if p.persistentDepletion ~= nil then
        PERSISTENT_DEPLETION = p.persistentDepletion
    end
end


-- ──────────────────────────────────────────────────────────────────────────────
-- STATIC CONFIGURATION  –  tune these to suit your campaign
-- ──────────────────────────────────────────────────────────────────────────────
local CFG = {
    -- How long (seconds) before BLUEFOR can rearm the same ship again (30 min)
    bluefor_rearm_cooldown  = 1800,

    -- Simulated logistics delay (seconds) before ammo is actually restored
    bluefor_rearm_delay     = 120,

    -- Fraction of full load restored per rearm visit (0.20 = +20% each visit)
    -- Both BLUEFOR and REDFOR use this; 5 visits are needed to reach 100%
    rearm_increment         = 0.20,

    -- How often (seconds) REDFOR ships are checked for low ammo (25 min)
    redfor_check_interval   = 1500,

    -- REDFOR ships are auto-rearmed when ammo drops below this fraction
    redfor_rearm_threshold  = 0.25,

    -- Set true to log REDFOR rearm events server-wide (useful for debugging)
    redfor_rearm_verbose    = false,

    -- How often (seconds) the state file is written during a mission (5 min)
    -- This is in addition to the S_EVENT_MISSION_END save.
    state_save_interval     = 300,
}


-- ──────────────────────────────────────────────────────────────────────────────
-- MODULE  –  internal state
-- ──────────────────────────────────────────────────────────────────────────────
local SW = {
    snapshots = {},   -- [unitName] = ammo table at mission start (= full load)
    lastRearm = {},   -- [unitName] = timer.getTime() of last successful rearm
    rearming  = {},   -- [unitName] = true while rearm delay is counting down
}


-- ──────────────────────────────────────────────────────────────────────────────
-- STATE FILE PATH
-- ──────────────────────────────────────────────────────────────────────────────
-- Resolves to <DCS Saved Games>/Scripts/RetributionShipWeapons.lua.
-- Returns nil if lfs is not available in this DCS environment.

local function getStatePath()
    local ok, lfs = pcall(require, "lfs")
    if not ok or not lfs then return nil end
    local dir = lfs.writedir() or ""
    if dir ~= "" and dir:sub(-1) ~= "/" and dir:sub(-1) ~= "\\" then
        dir = dir .. "/"
    end
    return dir .. "Scripts/RetributionShipWeapons.lua"
end


-- ──────────────────────────────────────────────────────────────────────────────
-- UTILITIES
-- ──────────────────────────────────────────────────────────────────────────────

--- Shallow copy of an ammo table.  Preserves the desc reference DCS uses
--- internally; only duplicates the count so the snapshot stays immutable.
local function copyAmmo(src)
    if not src then return {} end
    local dst = {}
    for i, slot in ipairs(src) do
        dst[i] = { desc = slot.desc, count = slot.count }
    end
    return dst
end

--- Sum all rounds/missiles in an ammo table.
local function totalAmmo(ammoTable)
    local n = 0
    if ammoTable then
        for _, slot in ipairs(ammoTable) do
            n = n + (slot.count or 0)
        end
    end
    return n
end

--- Current ammo as a fraction of the mission-start snapshot (0 – 1).
local function ammoRatio(unitName)
    local unit = Unit.getByName(unitName)
    if not unit or not unit:isExist() then return 0 end
    local snapTotal = totalAmmo(SW.snapshots[unitName])
    if snapTotal == 0 then return 1 end   -- no weapons recorded → treat as full
    return totalAmmo(unit:getAmmo()) / snapTotal
end

--- Collect all ship units for a coalition side.
local function getShips(side)
    local ships = {}
    local groups = coalition.getGroups(side, Group.Category.SHIP)
    if groups then
        for _, grp in ipairs(groups) do
            if grp and grp:isExist() then
                for _, u in ipairs(grp:getUnits()) do
                    if u and u:isExist() then
                        ships[#ships + 1] = u
                    end
                end
            end
        end
    end
    return ships
end

--- Number of +20% rearm visits still needed to reach full load.
local function visitsToFull(unitName)
    local ratio = ammoRatio(unitName)
    if ratio >= 1.0 then return 0 end
    return math.ceil((1.0 - ratio) / CFG.rearm_increment)
end


-- ──────────────────────────────────────────────────────────────────────────────
-- PERSISTENCE  –  save / load ammo ratios across Retribution turns
-- ──────────────────────────────────────────────────────────────────────────────

--- Serialize {unitName = ratio} as a Lua source file (return statement).
--- The file can be loaded back with loadstring() on the next mission start.
local function serializeState(ratios)
    local lines = {
        "-- DCS Retribution Ship Weapons State",
        "-- Auto-generated by ship_weapons plugin – do not edit by hand",
        "return {",
    }
    for unitName, ratio in pairs(ratios) do
        -- Escape backslashes and double-quotes inside the unit name string
        local escaped = unitName:gsub("\\", "\\\\"):gsub('"', '\\"')
        lines[#lines + 1] = string.format('    ["%s"] = %.6f,', escaped, ratio)
    end
    lines[#lines + 1] = "}"
    return table.concat(lines, "\n")
end

--- Write current ammo ratios to the state file.
--- Only ships that are still alive are saved; destroyed units are skipped
--- because Retribution will not place them in the next mission anyway.
local function saveState()
    if not PERSISTENT_DEPLETION then return end
    local path = getStatePath()
    if not path then return end

    local ratios = {}
    for unitName in pairs(SW.snapshots) do
        local unit = Unit.getByName(unitName)
        if unit and unit:isExist() then
            ratios[unitName] = ammoRatio(unitName)
        end
    end

    local f = io.open(path, "w")
    if not f then
        trigger.action.outText("[Ship Weapons] WARNING: could not write state file to:\n" .. path, 12)
        return
    end
    f:write(serializeState(ratios))
    f:close()
end

--- Load the state file written by the previous mission.
--- Returns an empty table on first run or if the file cannot be parsed.
local function loadState()
    if not PERSISTENT_DEPLETION then return {} end
    local path = getStatePath()
    if not path then return {} end

    local f = io.open(path, "r")
    if not f then return {} end          -- no file yet (first ever run)

    local content = f:read("*all")
    f:close()

    -- loadstring is Lua 5.1 / LuaJIT compatible (DCS uses LuaJIT)
    local fn = loadstring(content)
    if not fn then return {} end

    local ok, result = pcall(fn)
    if not ok or type(result) ~= "table" then return {} end

    return result
end

--- Apply saved ratios at mission start.
--- For each ship that has a matching saved ratio, we reduce its DCS-default
--- full load to that ratio before play begins.
local function applyPersistedState(savedRatios)
    local applied = 0
    for unitName, ratio in pairs(savedRatios) do
        local snap = SW.snapshots[unitName]
        if snap then
            local reducedAmmo = {}
            for i, slot in ipairs(snap) do
                reducedAmmo[i] = {
                    desc  = slot.desc,
                    count = math.max(0, math.floor(slot.count * ratio)),
                }
            end
            trigger.action.setAmmo(unitName, reducedAmmo)
            applied = applied + 1
        end
    end
    if applied > 0 then
        trigger.action.outText(
            string.format("[Ship Weapons] Carry-over depletion applied to %d ship(s) from last turn.",
                          applied), 15)
    end
end


-- ──────────────────────────────────────────────────────────────────────────────
-- CORE REARM  –  adds one increment (+20%) per visit, capped at snapshot max
-- ──────────────────────────────────────────────────────────────────────────────

--- Add CFG.rearm_increment of the full snapshot to the unit's current ammo.
--- Returns (true, newPct) on success or (false, errorString) on failure.
local function doRearm(unitName)
    local unit = Unit.getByName(unitName)
    if not unit or not unit:isExist() then
        return false, "unit destroyed or not found"
    end
    local snap = SW.snapshots[unitName]
    if not snap or #snap == 0 then
        return false, "no ammo snapshot available"
    end

    -- Index current ammo by desc reference so we can look it up per weapon type
    local currentCounts = {}
    for _, slot in ipairs(unit:getAmmo() or {}) do
        currentCounts[slot.desc] = slot.count
    end

    local newAmmo   = {}
    local newTotal  = 0
    local snapTotal = 0
    for i, snapSlot in ipairs(snap) do
        -- math.max(1, ...) ensures at least 1 round is added even for small magazines
        local increment = math.max(1, math.floor(snapSlot.count * CFG.rearm_increment))
        local cur       = currentCounts[snapSlot.desc] or 0
        local newCount  = math.min(cur + increment, snapSlot.count)
        newAmmo[i]      = { desc = snapSlot.desc, count = newCount }
        newTotal        = newTotal  + newCount
        snapTotal       = snapTotal + snapSlot.count
    end

    trigger.action.setAmmo(unitName, newAmmo)
    SW.lastRearm[unitName] = timer.getTime()

    local pct = snapTotal > 0 and math.floor(newTotal / snapTotal * 100) or 100
    return true, pct
end


-- ──────────────────────────────────────────────────────────────────────────────
-- BLUEFOR  –  F10 RADIO MENU
-- ──────────────────────────────────────────────────────────────────────────────

--- Handler: player checks ammo status of a ship.
local function onStatusRequest(unitName)
    local unit = Unit.getByName(unitName)
    if not unit or not unit:isExist() then
        trigger.action.outTextForCoalition(coalition.side.BLUE,
            "[Ship Weapons] " .. unitName .. " – unit not found or destroyed.", 10)
        return
    end

    local lines   = { "═══ " .. unitName .. " – Weapons Status ═══" }
    local current = unit:getAmmo()
    local snap    = SW.snapshots[unitName]

    if current and #current > 0 then
        for _, slot in ipairs(current) do
            local name      = (slot.desc and slot.desc.displayName) or "Unknown Weapon"
            local snapCount = 0
            if snap then
                for _, sslot in ipairs(snap) do
                    if sslot.desc == slot.desc then snapCount = sslot.count; break end
                end
            end
            lines[#lines + 1] = string.format("  %-30s %d / %d", name, slot.count, snapCount)
        end
    else
        lines[#lines + 1] = "  (No ammunition data available)"
    end

    -- Visual load bar
    local pct    = math.floor(ammoRatio(unitName) * 100)
    local filled = math.floor(pct / 10)
    local bar    = string.rep("█", filled) .. string.rep("░", 10 - filled)
    lines[#lines + 1] = string.format("\n  Load:  [%s] %d%%", bar, pct)

    -- Visits remaining to full load
    local visits = visitsToFull(unitName)
    if visits == 0 then
        lines[#lines + 1] = "  Status: FULLY LOADED"
    else
        lines[#lines + 1] = string.format(
            "  Visits to full load: %d × rearm needed (+%d%% each)",
            visits, math.floor(CFG.rearm_increment * 100))
    end

    -- Rearm cooldown display (minutes + seconds)
    local last = SW.lastRearm[unitName]
    if SW.rearming[unitName] then
        lines[#lines + 1] = "  Rearm: IN PROGRESS …"
    elseif last then
        local remaining = CFG.bluefor_rearm_cooldown - (timer.getTime() - last)
        if remaining > 0 then
            local mins = math.floor(remaining / 60)
            local secs = math.ceil(remaining % 60)
            lines[#lines + 1] = string.format("  Rearm cooldown: %d m %02d s remaining", mins, secs)
        else
            lines[#lines + 1] = "  Rearm: READY"
        end
    else
        lines[#lines + 1] = "  Rearm: READY"
    end

    if PERSISTENT_DEPLETION then
        lines[#lines + 1] = "  [Depletion carries over to next turn]"
    end

    trigger.action.outTextForCoalition(coalition.side.BLUE, table.concat(lines, "\n"), 25)
end

--- Handler: player triggers a rearm for a ship.
local function onRearmRequest(unitName)
    local unit = Unit.getByName(unitName)
    if not unit or not unit:isExist() then
        trigger.action.outTextForCoalition(coalition.side.BLUE,
            "[Ship Weapons] " .. unitName .. " – not found or destroyed.", 10)
        return
    end

    if SW.rearming[unitName] then
        trigger.action.outTextForCoalition(coalition.side.BLUE,
            "[Ship Weapons] " .. unitName .. " – rearm already in progress.", 10)
        return
    end

    local last = SW.lastRearm[unitName]
    if last then
        local remaining = CFG.bluefor_rearm_cooldown - (timer.getTime() - last)
        if remaining > 0 then
            local mins = math.floor(remaining / 60)
            local secs = math.ceil(remaining % 60)
            trigger.action.outTextForCoalition(coalition.side.BLUE,
                string.format("[Ship Weapons] %s – rearm on cooldown.  Ready in %d m %02d s.",
                              unitName, mins, secs), 12)
            return
        end
    end

    -- Begin rearm
    SW.rearming[unitName] = true
    trigger.action.outTextForCoalition(coalition.side.BLUE,
        string.format("[Ship Weapons] %s – rearm initiated.  ETA: %d s.",
                      unitName, CFG.bluefor_rearm_delay), 15)

    -- Complete after the logistics delay
    timer.scheduleFunction(function()
        SW.rearming[unitName] = nil
        local ok, result = doRearm(unitName)
        if ok then
            local visits = visitsToFull(unitName)
            local suffix = visits == 0
                and "Ship is at full load."
                or  string.format("%d more visit(s) needed to reach full load.", visits)
            trigger.action.outTextForCoalition(coalition.side.BLUE,
                string.format("[Ship Weapons] %s – rearm COMPLETE.  Load now %d%%.  %s",
                              unitName, result, suffix), 18)
        else
            trigger.action.outTextForCoalition(coalition.side.BLUE,
                "[Ship Weapons] " .. unitName .. " – rearm FAILED: " .. result, 12)
        end
    end, nil, timer.getTime() + CFG.bluefor_rearm_delay)
end

--- Build the F10 radio menu tree for BLUEFOR ships.
local function buildBlueforMenu()
    local root  = missionCommands.addSubMenuForCoalition(coalition.side.BLUE, "Ship Weapons", nil)
    local ships = getShips(coalition.side.BLUE)

    if #ships == 0 then
        missionCommands.addCommandForCoalition(
            coalition.side.BLUE, "(no ships detected)", root, function() end)
        return
    end

    for _, unit in ipairs(ships) do
        local uName = unit:getName()
        local gName = unit:getGroup():getName()
        local label = gName ~= uName and (gName .. " / " .. uName) or uName

        local shipMenu = missionCommands.addSubMenuForCoalition(coalition.side.BLUE, label, root)

        missionCommands.addCommandForCoalition(
            coalition.side.BLUE, "Rearm Ship",   shipMenu, onRearmRequest, uName)
        missionCommands.addCommandForCoalition(
            coalition.side.BLUE, "Ammo Status",  shipMenu, onStatusRequest, uName)
    end
end


-- ──────────────────────────────────────────────────────────────────────────────
-- REDFOR  –  AUTOMATIC AI REARM
-- ──────────────────────────────────────────────────────────────────────────────

--- Scheduled function: applies one rearm increment to any REDFOR ship below
--- the threshold.  One increment per cycle means a depleted ship needs multiple
--- cycles (up to 5 × 25 min = 2 h 5 min) to return to full readiness.
local function redforAutoRearm(_, time)
    local ships = getShips(coalition.side.RED)
    for _, unit in ipairs(ships) do
        local uName = unit:getName()
        if ammoRatio(uName) <= CFG.redfor_rearm_threshold then
            local ok, pct = doRearm(uName)
            if ok and CFG.redfor_rearm_verbose then
                trigger.action.outText(
                    string.format("[Ship Weapons] REDFOR %s auto-rearmed +%d%%.  Load now %d%%.",
                                  uName,
                                  math.floor(CFG.rearm_increment * 100),
                                  pct), 8)
            end
        end
    end
    return time + CFG.redfor_check_interval
end


-- ──────────────────────────────────────────────────────────────────────────────
-- MISSION END EVENT  –  save state before DCS closes the session
-- ──────────────────────────────────────────────────────────────────────────────

local missionEndHandler = {}
function missionEndHandler:onEvent(event)
    if event.id == world.event.S_EVENT_MISSION_END then
        saveState()
    end
end


-- ──────────────────────────────────────────────────────────────────────────────
-- PERIODIC STATE SAVE  –  belt-and-suspenders: also save on a timer
-- S_EVENT_MISSION_END is not always fired reliably in DCS; this ensures
-- we have a recent state snapshot even if the event is missed.
-- ──────────────────────────────────────────────────────────────────────────────

local function periodicSave(_, time)
    saveState()
    return time + CFG.state_save_interval
end


-- ──────────────────────────────────────────────────────────────────────────────
-- INITIALISATION
-- ──────────────────────────────────────────────────────────────────────────────

local function init()
    -- 1. Snapshot full ammo for every ship on both sides.
    --    This always reflects the DCS-default full load regardless of persistence.
    local function snapshotSide(side)
        for _, unit in ipairs(getShips(side)) do
            SW.snapshots[unit:getName()] = copyAmmo(unit:getAmmo() or {})
        end
    end
    snapshotSide(coalition.side.BLUE)
    snapshotSide(coalition.side.RED)

    -- 2. If persistent depletion is enabled, load the state saved by the
    --    previous mission and reduce each ship's starting ammo accordingly.
    if PERSISTENT_DEPLETION then
        local savedRatios = loadState()
        applyPersistedState(savedRatios)
    end

    -- 3. Build the BLUEFOR F10 radio menu.
    buildBlueforMenu()

    -- 4. Start the REDFOR auto-rearm scheduler.
    timer.scheduleFunction(redforAutoRearm, nil,
        timer.getTime() + CFG.redfor_check_interval)

    -- 5. Register state-save systems (only when persistence is on).
    if PERSISTENT_DEPLETION then
        world.addEventHandler(missionEndHandler)
        timer.scheduleFunction(periodicSave, nil,
            timer.getTime() + CFG.state_save_interval)
    end

    -- Startup banner
    trigger.action.outText(
        string.format(
            "[Ship Weapons] Plugin loaded.\n" ..
            "BLUEFOR : F10 → Ship Weapons | +%d%% per rearm | %d-min cooldown\n" ..
            "REDFOR  : auto-rearm every %d min when below %d%% | +%d%% per cycle\n" ..
            "Persistence: %s",
            math.floor(CFG.rearm_increment        * 100),
            math.floor(CFG.bluefor_rearm_cooldown / 60),
            math.floor(CFG.redfor_check_interval  / 60),
            math.floor(CFG.redfor_rearm_threshold  * 100),
            math.floor(CFG.rearm_increment         * 100),
            PERSISTENT_DEPLETION and "ON  (state saved to Scripts/RetributionShipWeapons.lua)"
                                 or  "OFF (ammo resets each mission)"),
        18)
end

init()
