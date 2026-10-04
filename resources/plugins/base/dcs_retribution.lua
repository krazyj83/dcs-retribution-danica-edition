-- the state.json file will be updated according to this schedule and on mission end
local WRITESTATE_SCHEDULE_IN_SECONDS = 15

logger = mist.Logger:new("DCSRetribution", "info")
logger:info("Check that json.lua is loaded : json = "..tostring(json))

crash_events = {} -- killed aircraft will be added via S_EVENT_CRASH event
dead_events = {} -- killed units will be added via S_EVENT_DEAD event
unit_lost_events = {} -- killed units will be added via S_EVENT_UNIT_LOST
kill_events = {} -- killed units will be added via S_EVENT_KILL 
base_capture_events = {}
destroyed_objects_positions = {} -- will be added via S_EVENT_DEAD event
mission_ended = false
dirty_state = false -- Track if state has changed and needs writing

-- Units placed in the mission file, name -> {coalition, category, type}:
-- everything Retribution generated plus anything added in the mission editor.
-- Deaths of these units are written as miz_unit_losses; the debrief keeps the
-- ones Retribution didn't generate (units added in the mission editor).
-- Units spawned while the mission runs (CTLD troops, respawns) aren't in the
-- mission file, so they are never counted.
local miz_units = {}
pcall(function()
    for side, coalition in pairs(env.mission and env.mission.coalition or {}) do
        for _, country in ipairs(coalition.country or {}) do
            for _, category in ipairs({"plane", "helicopter", "vehicle", "ship", "static"}) do
                local groups = country[category] and country[category].group or {}
                for _, group in ipairs(groups) do
                    for _, unit in ipairs(group.units or {}) do
                        if unit.name then
                            miz_units[unit.name] = {
                                coalition = side, category = category, type = unit.type,
                            }
                        end
                    end
                end
            end
        end
    end
end)
miz_unit_losses = {}
local miz_unit_lost = {}

-- Weapons fired by aircraft: unit name -> {weapon type name -> count}, from
-- S_EVENT_SHOT (guns aren't reported). After the mission the stores fired by
-- BLUEFOR aircraft come out of their base's weapon stores
-- (game/logistics/weapon_use.py).
weapons_fired = {}
local weapons_fired_count = 0

-- Player aircraft loading from the base's stores (logistics/ground_loading.py).
-- dcsRetributionWarehouses = {unmatched = n, bases = {{airbase, fuel_kg,
--   stores = {{key, per_store, count}, ...}}, ...}}
-- Each store (as Retribution counts it: a missile, a bomb or a rack) is matched
-- to the DCS weapon with the longest name contained in the store's name; DCS
-- weapons no store matches get `unmatched` so they can still be loaded.
local function norm(text)
    return (string.upper(text):gsub("[^A-Z0-9]", ""))
end

-- Fuel in each stocked airfield's DCS warehouse: airbase -> {start, left}, in
-- the units setLiquidAmount was given (kg). Whatever the aircraft took (players
-- and AI starting on the ground) is start - left; logistics/fuel.py charges it
-- instead of the full-tank estimate.
warehouse_fuel = {}

local function liquid_fuel(wh)
    local ok, amount = pcall(wh.getLiquidAmount, wh, 0)
    if ok and type(amount) == "number" then return amount end
    return nil
end

function retribution_setup_warehouses()
    local data = dcsRetributionWarehouses
    if not data or not data.bases or #data.bases == 0 then return end
    if not Warehouse or not Warehouse.getResourceMap then
        env.info("DCSRetribution|warehouses: no Warehouse API")
        return
    end
    local ok, map = pcall(Warehouse.getResourceMap)
    if not ok or type(map) ~= "table" then
        ok, map = pcall(Warehouse.getResourceMap, Warehouse)
    end
    if not ok or type(map) ~= "table" then
        env.info("DCSRetribution|warehouses: no resource map")
        return
    end
    local weapons = {}
    for name, ws in pairs(map) do
        if type(name) == "string" and string.sub(name, 1, 8) == "weapons." then
            local short = norm(string.match(name, "[^%.]+$") or name)
            if #short >= 4 then
                weapons[#weapons + 1] = {name = name, short = short}
            end
        end
    end
    -- The same store is at many bases: match each store key once.
    local match_cache = {}
    local function best_match(key)
        local cached = match_cache[key]
        if cached ~= nil then return cached or nil end
        local best = nil
        for _, weapon in ipairs(weapons) do
            if string.find(key, weapon.short, 1, true)
                and (not best or #weapon.short > #best.short) then
                best = weapon
            end
        end
        match_cache[key] = best or false
        return best
    end
    for _, base in ipairs(data.bases) do
        local airbase = Airbase.getByName(base.airbase)
        local wh = airbase and airbase.getWarehouse and airbase:getWarehouse()
        if wh then
            local counts = {}
            for _, store in ipairs(base.stores or {}) do
                local best = best_match(store.key)
                if best then
                    counts[best.name] = (counts[best.name] or 0)
                        + store.count * (store.per_store or 1)
                end
            end
            for _, weapon in ipairs(weapons) do
                pcall(wh.setItem, wh, weapon.name, counts[weapon.name] or data.unmatched or 500)
            end
            if base.fuel_kg then
                pcall(wh.setLiquidAmount, wh, 0, base.fuel_kg)
                local start = liquid_fuel(wh)
                if start then
                    warehouse_fuel[base.airbase] = {start = start}
                end
            end
            env.info("DCSRetribution|warehouses: stocked " .. base.airbase)
        end
    end
end

-- As early as possible (aircraft taking off later draw from the warehouse),
-- and again a second in, in case the data table was set after this script.
local warehouses_stocked = false
local function stock_warehouses()
    if warehouses_stocked or not dcsRetributionWarehouses then return nil end
    local ok, err = pcall(retribution_setup_warehouses)
    if ok then
        warehouses_stocked = true
    else
        env.info("DCSRetribution|warehouses failed: " .. tostring(err))
    end
    return nil
end
stock_warehouses()
timer.scheduleFunction(stock_warehouses, nil, timer.getTime() + 1)

-- What each player aircraft carried: weapons on board at takeoff less those on
-- board when it landed; everything on board if it was lost in the air.
-- player_ammo_used = {unit name = {weapon type = count}}.
player_ammo_used = {}
local player_airborne = {}  -- unit name -> ammo at takeoff

local function ammo_of(unit)
    local ammo = {}
    local ok, list = pcall(unit.getAmmo, unit)
    if ok and type(list) == "table" then
        for _, entry in ipairs(list) do
            local type_name = entry.desc and entry.desc.typeName
            if type_name then
                type_name = string.match(type_name, "[^%.]+$") or type_name
                ammo[type_name] = (ammo[type_name] or 0) + (entry.count or 0)
            end
        end
    end
    return ammo
end

local function is_player(unit)
    if not unit or not unit.getPlayerName then return false end
    local ok, name = pcall(unit.getPlayerName, unit)
    return ok and name ~= nil
end

local function add_used(name, taken, left)
    local used = player_ammo_used[name] or {}
    for type_name, count in pairs(taken) do
        local spent = count - ((left and left[type_name]) or 0)
        if spent > 0 then used[type_name] = (used[type_name] or 0) + spent end
    end
    if next(used) ~= nil then player_ammo_used[name] = used end
end

local function note_player_sortie(event)
    local unit = event.initiator
    if not is_player(unit) then return end
    local name = unit:getName()
    if event.id == world.event.S_EVENT_TAKEOFF then
        player_airborne[name] = ammo_of(unit)
    elseif event.id == world.event.S_EVENT_LAND and player_airborne[name] then
        add_used(name, player_airborne[name], ammo_of(unit))
        player_airborne[name] = nil
    end
end

local function note_player_lost(name)
    if name and player_airborne[name] then
        add_used(name, player_airborne[name], nil)
        player_airborne[name] = nil
    end
end

-- For write_state: sorties still in the air count what is used so far.
local function player_ammo_report()
    local report = {}
    for name, used in pairs(player_ammo_used) do
        report[name] = {}
        for t, n in pairs(used) do report[name][t] = n end
    end
    for name, taken in pairs(player_airborne) do
        local unit = Unit.getByName(name)
        local left = (unit and unit:isExist()) and ammo_of(unit) or nil
        local used = report[name] or {}
        for t, count in pairs(taken) do
            local spent = count - ((left and left[t]) or 0)
            if spent > 0 then used[t] = (used[t] or 0) + spent end
        end
        if next(used) ~= nil then report[name] = used end
    end
    return report
end

-- Only BLUEFOR aircraft: their stores are tracked. SAMs, ships and REDFOR
-- shoot a lot and would only grow the state file.
local function is_blue_aircraft(unit)
    if not unit.getCoalition or not unit.getDesc then return false end
    local ok_side, side = pcall(unit.getCoalition, unit)
    if not ok_side or side ~= coalition.side.BLUE then return false end
    local ok_desc, desc = pcall(unit.getDesc, unit)
    if not ok_desc or not desc then return false end
    return desc.category == Unit.Category.AIRPLANE
        or desc.category == Unit.Category.HELICOPTER
end

-- Returns true when the shot was recorded.
local function note_shot(event)
    local unit, weapon = event.initiator, event.weapon
    if not unit or not weapon or not unit.getName or not weapon.getTypeName then
        return false
    end
    if not is_blue_aircraft(unit) then
        return false
    end
    local ok_name, name = pcall(unit.getName, unit)
    local ok_type, type_name = pcall(weapon.getTypeName, weapon)
    if not ok_name or not ok_type or not name or not type_name then
        return false
    end
    local shots = weapons_fired[name]
    if not shots then
        shots = {}
        weapons_fired[name] = shots
        weapons_fired_count = weapons_fired_count + 1
    end
    shots[type_name] = (shots[type_name] or 0) + 1
    return true
end

local function note_miz_unit_loss(name)
    local info = name and miz_units[name]
    if info and not miz_unit_lost[name] then
        miz_unit_lost[name] = true
        miz_unit_losses[#miz_unit_losses + 1] = {
            name = name, coalition = info.coalition,
            category = info.category, type = info.type,
        }
    end
end

local function object_name(object)
    if not object or not object.getName then return nil end
    local ok, name = pcall(object.getName, object)
    return ok and name or nil
end

local function ends_with(str, ending)
   return ending == "" or str:sub(-#ending) == ending
end

local function messageAll(message)
    local msg = {}
    msg.text = message
    msg.displayTime = 25
    msg.msgFor = {coa = {'all'}}
    mist.message.add(msg)
end

-- Player-drawn convoys: vehicles that reached their route end.
-- dcsRetributionPlayerConvoys = {radius = m, convoys = {{group, x, z}, ...}}
-- is written by the mission generator (playerconvoygenerator.py). A vehicle
-- counts as arrived once it has been within `radius` of its route end; only
-- arrived vehicles are delivered to the destination base after the mission.
player_convoy_arrived = player_convoy_arrived or {}

function retribution_check_player_convoys()
    local data = dcsRetributionPlayerConvoys
    if type(data) ~= "table" or type(data.convoys) ~= "table" then
        return
    end
    local radius = tonumber(data.radius) or 2000
    for _, convoy in ipairs(data.convoys) do
        local group = Group.getByName(convoy.group)
        if group and group:isExist() then
            for _, unit in ipairs(group:getUnits() or {}) do
                if unit and unit:isExist() and unit:getLife() > 0 then
                    local p = unit:getPoint()
                    local dx, dz = p.x - convoy.x, p.z - convoy.z
                    if dx * dx + dz * dz <= radius * radius then
                        player_convoy_arrived[unit:getName()] = true
                    end
                end
            end
        end
    end
end

-- Held convoys: a route with a Convoy Escort flight waits at its start (a
-- Hold task stopped by `flag`) until one of the escort aircraft (`escorts`,
-- unit names) is airborne within data.escortRadius of the start, or until
-- data.escortWait seconds have passed. The Hold task also stops by itself
-- after that time, should this script not run.
player_convoy_released = player_convoy_released or {}

function retribution_release_player_convoys()
    local data = dcsRetributionPlayerConvoys
    if type(data) ~= "table" or type(data.convoys) ~= "table" then
        return
    end
    local radius = tonumber(data.escortRadius) or 9260
    local wait = tonumber(data.escortWait) or 3600
    for _, convoy in ipairs(data.convoys) do
        if convoy.flag and not player_convoy_released[convoy.flag] then
            local escorted = false
            for _, name in ipairs(convoy.escorts or {}) do
                local unit = Unit.getByName(name)
                if unit and unit:isExist() and unit:inAir() then
                    local p = unit:getPoint()
                    local dx, dz = p.x - convoy.startX, p.z - convoy.startZ
                    if dx * dx + dz * dz <= radius * radius then
                        escorted = true
                        break
                    end
                end
            end
            local timed_out = timer.getTime() >= wait
            if escorted or timed_out then
                player_convoy_released[convoy.flag] = true
                trigger.action.setUserFlag(convoy.flag, true)
                local label = tostring(convoy.label or convoy.group)
                local text = escorted
                    and ("Convoy " .. label .. ": escort on station, moving out.")
                    or ("Convoy " .. label .. ": no escort, moving out alone.")
                trigger.action.outTextForCoalition(coalition.side.BLUE, text, 15)
            end
        end
    end
end

timer.scheduleFunction(function(_, t)
    pcall(retribution_release_player_convoys)
    return t + 5
end, nil, timer.getTime() + 5)

local function player_convoy_arrivals()
    pcall(retribution_check_player_convoys)
    local names = {}
    for name, _ in pairs(player_convoy_arrived) do
        names[#names + 1] = name
    end
    return names
end

timer.scheduleFunction(function(_, t)
    pcall(retribution_check_player_convoys)
    return t + 15
end, nil, timer.getTime() + 15)

local function warehouse_fuel_report()
    local report = {}
    for name, fuel in pairs(warehouse_fuel) do
        local airbase = Airbase.getByName(name)
        local wh = airbase and airbase.getWarehouse and airbase:getWarehouse()
        local left = wh and liquid_fuel(wh)
        if left then
            report[name] = {start = fuel.start, left = left}
        end
    end
    return report
end

function write_state()
    local _debriefing_file_location = debriefing_file_location
    if not debriefing_file_location or debriefing_file_location == "" then
        error("Unable to save DCS Retribution state: debriefing file path is unavailable")
    end

    if not json then
        error("Unable to save DCS Retribution state, JSON library is not loaded")
    end

    local fp, open_error = io.open(_debriefing_file_location, 'w')
    if not fp then
        error("Unable to open state file for writing: "..tostring(_debriefing_file_location).." ("..tostring(open_error)..")")
    end
    local game_state = {
        ["crash_events"] = crash_events,
        ["dead_events"] = dead_events,
        ["base_capture_events"] = base_capture_events,
		["unit_lost_events"] = unit_lost_events,
		["kill_events"] = kill_events,
        ["mission_ended"] = mission_ended,
        ["destroyed_objects_positions"] = destroyed_objects_positions,
    }
    -- Cargo crates of weapon transfers (retribution_cargo.lua), if any.
    if retribution_cargo_state then
        local cargo_ok, cargo_crates = pcall(retribution_cargo_state)
        if cargo_ok and cargo_crates and #cargo_crates > 0 then
            game_state["cargo_crates"] = cargo_crates
        end
    end
    -- CTLD groups still alive (ctld_garrison.lua): they stay in the campaign.
    if retribution_ctld_garrison_state then
        local garrison_ok, garrison = pcall(retribution_ctld_garrison_state)
        if garrison_ok and garrison then
            game_state["ctld_garrison"] = garrison
        end
    end
    -- What player aircraft carried (see note_player_sortie above), if any.
    local ammo_used = player_ammo_report()
    if next(ammo_used) ~= nil then
        game_state["player_ammo_used"] = ammo_used
    end
    -- Fuel taken from the stocked airfield warehouses, if any.
    local fuel_ok, fuel_report = pcall(warehouse_fuel_report)
    if fuel_ok and next(fuel_report) ~= nil then
        game_state["warehouse_fuel"] = fuel_report
    end
    -- Weapons fired by aircraft (see note_shot above), if any.
    if weapons_fired_count > 0 then
        game_state["weapons_fired"] = weapons_fired
    end
    -- Mission-file units that were lost (see miz_units above), if any.
    if #miz_unit_losses > 0 then
        game_state["miz_unit_losses"] = miz_unit_losses
    end
    -- Player-drawn convoy vehicles that reached their route end, if any.
    local arrivals = player_convoy_arrivals()
    if #arrivals > 0 then
        game_state["player_convoy_arrivals"] = arrivals
    end
    -- Naval munitions crates (ship_weapons plugin), if any.
    if retribution_naval_state then
        local naval_ok, naval = pcall(retribution_naval_state)
        if naval_ok and naval and #naval > 0 then
            game_state["naval_munitions"] = naval
        end
    end
    local ok, write_error = pcall(function()
        fp:write(json:encode(game_state))
    end)
    fp:close()
    if not ok then
        error(write_error)
    end
end

local function canWrite(name)
    local f = io.open(name, "a")
    if f then
        f:close()
        return true
    end
    return false
end

local function testDebriefingFilePath(folderPath, folderName, useCurrentStamping)
    if folderPath then
        local filePath = nil
        if not ends_with(folderPath, "\\") then
            folderPath = folderPath .. "\\"
        end
        if useCurrentStamping then
            filePath = string.format("%sstate-%s.json",folderPath, tostring(os.time()))
        else 
            filePath = string.format("%sstate.json",folderPath)
        end
        local isOk = canWrite(filePath)
        if isOk then 
            logger:info(string.format("The state.json file will be created in %s : (%s)",folderName, filePath))
            return filePath
        end
    end
    return nil
end

local function discoverDebriefingFilePath()   
    -- establish a search pattern into the following modes
    -- 1. Environment variable RETRIBUTION_EXPORT_DIR, to support dedicated server hosting
    -- 2. Embedded DCS Retribution dcsRetribution.installPath (set by the app to its install path), to support locally hosted single player
    -- 3. System temporary folder, as set in the TEMP environment variable
    -- 4. Working directory.
    
    local useCurrentStamping = nil
    if os then  
        useCurrentStamping = os.getenv("RETRIBUTION_EXPORT_STAMPED_STATE")
    end

    local installPath = nil
    if dcsRetribution then
        installPath = dcsRetribution.installPath
    end
    
    if os then
        local result = nil
        -- try using the RETRIBUTION_EXPORT_DIR environment variable
        result = testDebriefingFilePath(os.getenv("RETRIBUTION_EXPORT_DIR"), "RETRIBUTION_EXPORT_DIR", useCurrentStamping)
        if result then
            return result
        end
        -- no joy ? maybe there is a valid path in the mission ?
        result = testDebriefingFilePath(installPath, "the DCS Retribution install folder", useCurrentStamping)
        if result then
            return result
        end
        -- there's always the possibility of using the system temporary folder
        result = testDebriefingFilePath(os.getenv("TEMP"), "TEMP", useCurrentStamping)
        if result then
            return result
        end
    end

    -- nothing worked, let's try the last resort folder : current directory.
    if lfs then
        return testDebriefingFilePath(lfs.writedir().."Missions\\", "the working directory", useCurrentStamping)
    end
    
    return nil
end

debriefing_file_location = discoverDebriefingFilePath()
local error_message_shown = false

write_state_error_handling = function()
    local _debriefing_file_location = debriefing_file_location
    if not debriefing_file_location then 
        _debriefing_file_location = "[nil]"
        logger:error("Unable to find where to write DCS Retribution state")
    end

    -- Only write if state has changed since last write
    if dirty_state then
        if pcall(write_state) then
            dirty_state = false -- Reset dirty flag after successful write
            error_message_shown = false
        else
            if not error_message_shown then
                messageAll("Unable to write DCS Retribution state to ".._debriefing_file_location..
                        "\nYou can abort the mission in DCS Retribution.\n"..
                        "\n\nPlease fix your setup in DCS Retribution, make sure you are pointing to the right installation directory from the File/Preferences menu. Then after fixing the path restart DCS Retribution, and then restart DCS."..
                        "\n\nYou can also try to fix the issue manually by replacing the file <dcs_installation_directory>/Scripts/MissionScripting.lua by the one provided there : <dcs_retribution_folder>/resources/scripts/MissionScripting.lua. And then restart DCS. (This will also have to be done again after each DCS update)"..
                        "\n\nIt's not worth playing, the state of the mission will not be recorded.")
                error_message_shown = true
            end
        end
    end

    -- Reschedule quickly if mission is over and we still have unsaved changes,
    -- otherwise use the normal cadence.
    local next_schedule_in_seconds = WRITESTATE_SCHEDULE_IN_SECONDS
    if mission_ended and dirty_state then
        next_schedule_in_seconds = 1
    end
    mist.scheduleFunction(write_state_error_handling, {}, timer.getTime() + next_schedule_in_seconds)
end

-- Units being replaced by a respawn in place (ship_weapons rearm): unit name ->
-- time until which their removal is not a loss.
retribution_respawning = retribution_respawning or {}
local function being_respawned(event)
    local unit = event.initiator or event.target
    if not unit or not unit.getName then return false end
    local ok, name = pcall(unit.getName, unit)
    local until_t = ok and retribution_respawning[name]
    return until_t ~= nil and until_t ~= false and timer.getTime() <= until_t
end

local function onEvent(event)
    if being_respawned(event) then
        return
    end
    if event.id == world.event.S_EVENT_SHOT then
        if note_shot(event) then
            dirty_state = true
        end
        return
    end
    if event.id == world.event.S_EVENT_TAKEOFF or event.id == world.event.S_EVENT_LAND then
        note_player_sortie(event)
        dirty_state = true
    end
    if event.id == world.event.S_EVENT_CRASH or event.id == world.event.S_EVENT_DEAD
        or event.id == world.event.S_EVENT_PILOT_DEAD or event.id == world.event.S_EVENT_EJECTION
        or event.id == world.event.S_EVENT_UNIT_LOST then
        note_player_lost(object_name(event.initiator))
    end

    if event.id == world.event.S_EVENT_CRASH or event.id == world.event.S_EVENT_UNIT_LOST
        or event.id == world.event.S_EVENT_DEAD then
        note_miz_unit_loss(object_name(event.initiator))
    elseif event.id == world.event.S_EVENT_KILL then
        note_miz_unit_loss(object_name(event.target))
    end

    if event.id == world.event.S_EVENT_CRASH and event.initiator then
        crash_events[#crash_events + 1] = event.initiator.getName(event.initiator)
        dirty_state = true
    end
   
    if event.id == world.event.S_EVENT_UNIT_LOST and event.initiator then
        unit_lost_events[#unit_lost_events + 1] = event.initiator.getName(event.initiator)
        dirty_state = true
    end
	
	if event.id == world.event.S_EVENT_KILL and event.target then
        kill_events[#kill_events + 1] = event.target.getName(event.target)
        dirty_state = true
    end

    if event.id == world.event.S_EVENT_DEAD and event.initiator and event.initiator.getName then
        dead_events[#dead_events + 1] = event.initiator.getName(event.initiator)
        local position = event.initiator.getPosition(event.initiator)
        local destruction = {}
        destruction.x = position.p.x
        destruction.y = position.p.y
        destruction.z = position.p.z
        destruction.type = event.initiator:getTypeName()
        destruction.orientation = mist.getHeading(event.initiator) * 57.3
        -- Only track actual units/buildings, not debris/crash models
        if destruction.type ~= nil and 
           string.find(destruction.type, "GENERIC_CRASH_MODEL") == nil and
           string.find(destruction.type, "_CRASH") == nil then
            destroyed_objects_positions[#destroyed_objects_positions + 1] = destruction
        end
        dirty_state = true
    end

    if event.id == world.event.S_EVENT_MISSION_END then
        mission_ended = true
        dirty_state = true
        if pcall(write_state) then
            dirty_state = false
        end
    end

end

mist.addEventHandler(onEvent)

dirty_state = true
write_state_error_handling()

-- Escort leash
-- Escorts are kept within their engagement range relative to the escorted group.
-- This is driven by the mission-injected dcsRetribution.Escorts table.

local function escort_leash_get_group(id)
    local group_id = tonumber(id)
    if not group_id or group_id <= 0 then
        return nil
    end
    -- DCS has no Group.getByID; resolve the mission group id to a name via mist.
    local data = mist.DBs.groupsById and mist.DBs.groupsById[group_id]
    return data and Group.getByName(data.groupName) or nil
end

local function escort_leash_set_roe(group, roe)
    if not group then
        return
    end
    local controller = group:getController()
    if controller then
        controller:setOption(AI.Option.Air.id.ROE, roe)
    end
end

local function escort_leash_update()
    -- Keep running even if dcsRetribution data isn't available yet (trigger ordering)
    if not dcsRetribution or type(dcsRetribution.Escorts) ~= "table" then
        return timer.getTime() + 10
    end

    for _, pair in pairs(dcsRetribution.Escorts) do
        local escort_group = escort_leash_get_group(pair.escortGroupId)
        local escorted_group = escort_leash_get_group(pair.escortedGroupId)

        -- If the escorted group no longer exists (dead/despawned), ensure escort isn't stuck.
        if escort_group and not escorted_group then
            escort_leash_set_roe(escort_group, AI.Option.Air.val.ROE.OPEN_FIRE)
        elseif escort_group and escorted_group then
            local escort_unit = escort_group:getUnit(1)
            local escorted_unit = escorted_group:getUnit(1)
            if escort_unit and escorted_unit then
                local escort_pos = escort_unit:getPoint()
                local escorted_pos = escorted_unit:getPoint()
                local dx = escort_pos.x - escorted_pos.x
                local dz = escort_pos.z - escorted_pos.z
                local distance = math.sqrt(dx * dx + dz * dz)

                local max_dist = tonumber(pair.engagementRangeMeters) or 0
                if max_dist > 0 and distance > max_dist then
                    escort_leash_set_roe(escort_group, AI.Option.Air.val.ROE.RETURN_FIRE)
                else
                    escort_leash_set_roe(escort_group, AI.Option.Air.val.ROE.OPEN_FIRE)
                end
            end
        end
    end

    return timer.getTime() + 10
end

timer.scheduleFunction(escort_leash_update, nil, timer.getTime() + 1)
