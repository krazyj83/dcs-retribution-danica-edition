-- ctld_garrison.lua
--
-- CTLD troops stay in the campaign (game/livingworld/garrison.py).
--
-- 1. Hand back: the groups Retribution placed from last mission's garrison
--    (dcsRetributionGarrison.groups = {{name, side, kind}}) are added to
--    CTLD's dropped-group lists once CTLD has started, so pilots can pick
--    them up and move them like any troops they unloaded.
-- 2. Report: retribution_ctld_garrison_state() lists every CTLD-dropped group
--    still alive (both sides, troops and vehicles) unit by unit, with type,
--    position and heading. dcs_retribution.lua's write_state() puts it into
--    state.json as "ctld_garrison".
--
-- Does nothing without CTLD: no hand-back, and the report is nil (Retribution
-- then keeps its garrison as it was).

RetributionGarrison = RetributionGarrison or {}

local HAND_BACK_DELAY = 8 -- seconds; CTLD initialises at t+2
local HAND_BACK_TRIES = 20

local function ctld_lists()
    if not ctld or not ctld.droppedTroopsBLUE then
        return nil
    end
    return {
        { list = ctld.droppedTroopsBLUE, side = 2, kind = "troops" },
        { list = ctld.droppedTroopsRED, side = 1, kind = "troops" },
        { list = ctld.droppedVehiclesBLUE, side = 2, kind = "vehicles" },
        { list = ctld.droppedVehiclesRED, side = 1, kind = "vehicles" },
    }
end

local function list_for(side, kind)
    for _, entry in ipairs(ctld_lists() or {}) do
        if entry.side == side and entry.kind == kind then
            return entry.list
        end
    end
    return nil
end

function RetributionGarrison.hand_back(_, time)
    local data = dcsRetributionGarrison
    if not data or not data.groups then
        return nil
    end
    if not ctld_lists() then
        RetributionGarrison.tries = (RetributionGarrison.tries or 0) + 1
        if RetributionGarrison.tries < HAND_BACK_TRIES then
            return (time or timer.getTime()) + 5
        end
        env.info("ctld_garrison: CTLD not running, garrison not handed back")
        return nil
    end
    local handed = 0
    for _, g in ipairs(data.groups) do
        local list = list_for(tonumber(g.side), g.kind)
        if list and Group.getByName(g.name) then
            table.insert(list, g.name)
            handed = handed + 1
        end
    end
    env.info("ctld_garrison: " .. handed .. " group(s) handed to CTLD")
    return nil
end

local function heading_of(unit)
    local ok, pos = pcall(function() return unit:getPosition() end)
    if not ok or not pos then
        return 0
    end
    local h = math.atan2(pos.x.z, pos.x.x)
    if h < 0 then
        h = h + 2 * math.pi
    end
    return h
end

function retribution_ctld_garrison_state()
    local lists = ctld_lists()
    if not lists then
        return nil
    end
    local seen, groups = {}, {}
    for _, entry in ipairs(lists) do
        for _, name in pairs(entry.list) do
            if type(name) == "string" and not seen[name] then
                seen[name] = true
                local group = Group.getByName(name)
                if group and group:isExist() then
                    local units = {}
                    for _, unit in ipairs(group:getUnits() or {}) do
                        if unit and unit:isExist() and unit:getLife() > 0 then
                            local p = unit:getPoint()
                            units[#units + 1] = {
                                type = unit:getTypeName(),
                                x = p.x,
                                z = p.z,
                                heading = heading_of(unit),
                            }
                        end
                    end
                    if #units > 0 then
                        groups[#groups + 1] = {
                            name = name,
                            side = entry.side,
                            kind = entry.kind,
                            units = units,
                        }
                    end
                end
            end
        end
    end
    return { groups = groups }
end

if not RetributionGarrison.no_autorun then
    timer.scheduleFunction(RetributionGarrison.hand_back, nil, timer.getTime() + HAND_BACK_DELAY)
end
