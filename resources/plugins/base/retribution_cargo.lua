-- DCS Retribution: cargo for weapon transfers (LOGISTIC flights).
--
-- * Client LOGISTIC flights get an F10 "Cargo" menu. Landed at a friendly base,
--   the pilot can order crates from that base's weapon stock:
--   F10 > Cargo > Order at <base> > <category> > <weapon> > <quantity>.
--   The crate appears beside the aircraft, with its real mass. Orders that are
--   too heavy for the aircraft at its current fuel are refused.
-- * Every cargo crate (planned in Retribution or ordered here) is reported in
--   state.json ("cargo_crates"): where it is, whether it still exists, whether
--   it was destroyed. Retribution delivers a crate to the friendly base it was
--   set down at.
--
-- Data comes from the mission-injected dcsRetributionCargo table:
--   flights[groupName] = {tid, helicopter, emptyKg, maxKg, fuelMaxKg}
--   bases  = {{id, name, x, z, radius}, ...}
--   stock[baseId] = {{clsid, name, category, kg, qty}, ...}
--   crates = {{name, tid, source, contents = {{clsid, count}}}, ...}

local CRATE_TYPE = "ammo_cargo"
local CRATE_SHAPE = "ammo_box_cargo"
local HELI_SIDE_OFFSET_M = 25
local PLANE_BEHIND_OFFSET_M = 35
local CRATE_SPACING_M = 5
local ITEMS_PER_MENU_PAGE = 9
local QUANTITIES = {1, 2, 4, 10, 20}
local KG_TO_LB = 2.20462

local RC = {crates = {}, groups = {}, sequence = 0, ready = false}
retribution_cargo = RC

local function cargoData()
    return dcsRetributionCargo
end

local function lb(kg)
    return math.floor(kg * KG_TO_LB + 0.5)
end

local function message(groupId, text, seconds)
    trigger.action.outTextForGroup(groupId, text, seconds or 12)
end

local function markDirty()
    dirty_state = true -- picked up by dcs_retribution.lua's state writer
end

local function distance2d(ax, az, bx, bz)
    local dx, dz = ax - bx, az - bz
    return math.sqrt(dx * dx + dz * dz)
end

local function baseAt(point)
    local best, bestDistance = nil, nil
    for _, base in ipairs(cargoData().bases or {}) do
        local d = distance2d(point.x, point.z, base.x, base.z)
        if d <= base.radius and (bestDistance == nil or d < bestDistance) then
            best, bestDistance = base, d
        end
    end
    return best
end

local function baseName(id)
    for _, base in ipairs(cargoData().bases or {}) do
        if base.id == id then
            return base.name
        end
    end
    return "?"
end

local function leadUnit(groupName)
    local group = Group.getByName(groupName)
    if not group or not group:isExist() then
        return nil, nil
    end
    local unit = group:getUnit(1)
    if not unit or not unit:isExist() then
        return group, nil
    end
    return group, unit
end

local function shortName(name)
    if string.len(name) > 40 then
        return string.sub(name, 1, 38) .. ".."
    end
    return name
end

-- Adds entries under parent, 9 per page with a "More..." submenu.
local function addPaged(groupId, parent, entries, addEntry)
    local menu = parent
    for i, entry in ipairs(entries) do
        if i > 1 and (i - 1) % ITEMS_PER_MENU_PAGE == 0 then
            menu = missionCommands.addSubMenuForGroup(groupId, "More...", menu)
        end
        addEntry(menu, entry)
    end
end

-- ── Crate status (reported to Retribution) ────────────────────────────

function retribution_cargo_state()
    local out = {}
    for name, crate in pairs(RC.crates) do
        local entry = {
            name = name,
            tid = crate.tid,
            source = crate.source,
            contents = crate.contents,
            requested = crate.requested,
            destroyed = crate.destroyed,
            exists = false,
        }
        local object = StaticObject.getByName(name)
        if object and object:isExist() then
            local p = object:getPoint()
            entry.exists = true
            entry.x = p.x
            entry.z = p.z
            entry.agl = p.y - land.getHeight({x = p.x, y = p.z})
        end
        out[#out + 1] = entry
    end
    return out
end

-- ── Menu actions ───────────────────────────────────────────────────────

local function order(args)
    local group, unit = leadUnit(args.group)
    if not unit then
        return
    end
    local groupId = group:getID()
    local flight = cargoData().flights[args.group]
    if unit:inAir() then
        message(groupId, "Land at the base before ordering cargo.")
        return
    end
    local base = baseAt(unit:getPoint())
    if not base or base.id ~= args.base then
        message(groupId, "You are no longer at " .. baseName(args.base) .. ".")
        return
    end
    local item = cargoData().stock[args.base][args.index]
    if item.qty < args.count then
        message(groupId, string.format("Only %d %s left at %s.", item.qty, item.name, base.name))
        return
    end
    local mass = item.kg * args.count
    if flight.maxKg then
        local fuelKg = unit:getFuel() * flight.fuelMaxKg
        local room = flight.maxKg - flight.emptyKg - fuelKg
        if mass > room then
            message(groupId, string.format(
                "Too heavy: %d lb. You can lift %d lb of cargo at your current fuel.",
                lb(mass), lb(math.max(0, room))))
            return
        end
    end

    local state = RC.groups[args.group]
    RC.sequence = RC.sequence + 1
    local position = unit:getPosition()
    local heading = math.atan2(position.x.z, position.x.x)
    local direction, offset
    if flight.helicopter then
        direction = heading + math.pi / 2
        offset = HELI_SIDE_OFFSET_M
    else
        direction = heading + math.pi
        offset = PLANE_BEHIND_OFFSET_M
    end
    offset = offset + CRATE_SPACING_M * (#state.orders % 4)
    local x = position.p.x + math.cos(direction) * offset
    local z = position.p.z + math.sin(direction) * offset
    local name = string.format("Cargo %s R%d: %dx %s", flight.tid, RC.sequence, args.count, item.name)
    coalition.addStaticObject(unit:getCountry(), {
        category = "Cargos",
        type = CRATE_TYPE,
        shape_name = CRATE_SHAPE,
        name = name,
        x = x,
        y = z,
        heading = heading,
        canCargo = true,
        mass = mass,
    })
    item.qty = item.qty - args.count
    RC.crates[name] = {
        tid = flight.tid,
        source = args.base,
        contents = {{clsid = item.clsid, count = args.count}},
        requested = true,
        destroyed = false,
        spawnX = x,
        spawnZ = z,
        group = args.group,
    }
    state.orders[#state.orders + 1] = name
    markDirty()
    message(groupId, string.format(
        "%dx %s (%d lb) is waiting %d m %s of you.\nCrate: %s\n%d left at %s.",
        args.count, item.name, lb(mass), offset,
        flight.helicopter and "to the right" or "behind", name, item.qty, base.name))
end

local function cancelLast(groupName)
    local group, unit = leadUnit(groupName)
    if not group then
        return
    end
    local groupId = group:getID()
    local state = RC.groups[groupName]
    local name = state.orders[#state.orders]
    if not name then
        message(groupId, "Nothing ordered to cancel.")
        return
    end
    local crate = RC.crates[name]
    local object = StaticObject.getByName(name)
    if object and object:isExist() then
        local p = object:getPoint()
        if distance2d(p.x, p.z, crate.spawnX, crate.spawnZ) > 5 then
            message(groupId, "That crate has been moved; it can't be cancelled.")
            return
        end
        object:destroy()
    end
    for _, item in ipairs(cargoData().stock[crate.source] or {}) do
        if item.clsid == crate.contents[1].clsid then
            item.qty = item.qty + crate.contents[1].count
            break
        end
    end
    RC.crates[name] = nil
    state.orders[#state.orders] = nil
    markDirty()
    message(groupId, "Cancelled: " .. name)
end

local function status(groupName)
    local group, unit = leadUnit(groupName)
    if not group then
        return
    end
    local flight = cargoData().flights[groupName]
    local lines = {}
    for name, crate in pairs(RC.crates) do
        if crate.tid == flight.tid then
            local where
            local object = StaticObject.getByName(name)
            if crate.destroyed then
                where = "destroyed"
            elseif object and object:isExist() then
                local p = object:getPoint()
                local agl = p.y - land.getHeight({x = p.x, y = p.z})
                local base = baseAt(p)
                if agl > 3 then
                    where = "in the air"
                elseif base then
                    where = "on the ground at " .. base.name
                else
                    where = "on the ground away from any base"
                end
            else
                where = "loaded / not visible"
            end
            lines[#lines + 1] = name .. " - " .. where
        end
    end
    if #lines == 0 then
        lines[1] = "No cargo for this flight yet."
    end
    table.sort(lines)
    message(group:getID(), table.concat(lines, "\n"), 20)
end

-- ── Menus ──────────────────────────────────────────────────────────────

function RC.buildMenu(groupName)
    local flight = cargoData().flights[groupName]
    local group, unit = leadUnit(groupName)
    if not flight or not group then
        return
    end
    local groupId = group:getID()
    local state = RC.groups[groupName] or {orders = {}}
    RC.groups[groupName] = state
    if state.root then
        missionCommands.removeItemForGroup(groupId, state.root)
    end
    local root = missionCommands.addSubMenuForGroup(groupId, "Cargo")
    state.root = root
    missionCommands.addCommandForGroup(groupId, "Cargo status", root, status, groupName)

    local base = nil
    if unit and not unit:inAir() then
        base = baseAt(unit:getPoint())
    end
    if not base then
        missionCommands.addCommandForGroup(groupId, "Land at a friendly base to order cargo", root,
            function() message(groupId, "Land at a friendly base to order cargo.") end)
        return
    end
    missionCommands.addCommandForGroup(groupId, "Cancel last order", root, cancelLast, groupName)
    local stock = cargoData().stock[base.id] or {}
    if #stock == 0 then
        missionCommands.addCommandForGroup(groupId, "No weapons in stock at " .. base.name, root,
            function() message(groupId, "No weapons in stock at " .. base.name .. ".") end)
        return
    end

    local orderMenu = missionCommands.addSubMenuForGroup(groupId, "Order at " .. base.name, root)
    local byCategory, categories = {}, {}
    for index, item in ipairs(stock) do
        if not byCategory[item.category] then
            byCategory[item.category] = {}
            categories[#categories + 1] = item.category
        end
        table.insert(byCategory[item.category], index)
    end
    table.sort(categories)
    addPaged(groupId, orderMenu, categories, function(parent, category)
        local categoryMenu = missionCommands.addSubMenuForGroup(groupId, category, parent)
        addPaged(groupId, categoryMenu, byCategory[category], function(parent2, index)
            local item = stock[index]
            local weaponMenu = missionCommands.addSubMenuForGroup(
                groupId, string.format("%s (%d lb)", shortName(item.name), lb(item.kg)), parent2)
            for _, count in ipairs(QUANTITIES) do
                missionCommands.addCommandForGroup(groupId,
                    string.format("%d  (%d lb)", count, lb(count * item.kg)), weaponMenu,
                    order, {group = groupName, base = base.id, index = index, count = count})
            end
        end)
    end)
end

local function rebuildLater(groupName)
    timer.scheduleFunction(function()
        local ok, err = pcall(RC.buildMenu, groupName)
        if not ok then
            env.error("retribution_cargo: menu for " .. groupName .. " failed: " .. tostring(err))
        end
    end, nil, timer.getTime() + 1)
end

-- ── Events ─────────────────────────────────────────────────────────────

local handler = {}
function handler:onEvent(event)
    if not RC.ready or not event.initiator then
        return
    end
    local ok, name = pcall(function() return event.initiator:getName() end)
    if not ok or not name then
        return
    end
    if event.id == world.event.S_EVENT_DEAD and RC.crates[name] then
        RC.crates[name].destroyed = true
        markDirty()
        return
    end
    if event.id == world.event.S_EVENT_BIRTH or event.id == world.event.S_EVENT_LAND
            or event.id == world.event.S_EVENT_TAKEOFF
            or event.id == world.event.S_EVENT_RUNWAY_TAKEOFF
            or event.id == world.event.S_EVENT_RUNWAY_TOUCH then
        local gok, group = pcall(function() return event.initiator:getGroup() end)
        if gok and group then
            local groupName = group:getName()
            if cargoData().flights[groupName] then
                rebuildLater(groupName)
            end
        end
    end
end

-- ── Start-up ───────────────────────────────────────────────────────────

local attempts = 0
local function init()
    attempts = attempts + 1
    if not cargoData() then
        if attempts < 30 then
            return timer.getTime() + 2 -- data trigger may run after this script
        end
        return nil -- no LOGISTIC client flights in this mission
    end
    for _, crate in ipairs(cargoData().crates or {}) do
        RC.crates[crate.name] = {
            tid = crate.tid,
            source = crate.source,
            contents = crate.contents,
            requested = false,
            destroyed = false,
        }
    end
    RC.ready = true
    world.addEventHandler(handler)
    for groupName, _ in pairs(cargoData().flights or {}) do
        rebuildLater(groupName)
    end
    -- Crates move without events (sling loads): refresh the state regularly.
    timer.scheduleFunction(function()
        markDirty()
        return timer.getTime() + 30
    end, nil, timer.getTime() + 30)
    markDirty()
    env.info("retribution_cargo: ready")
    return nil
end

timer.scheduleFunction(init, nil, timer.getTime() + 1)
