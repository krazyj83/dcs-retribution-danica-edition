-- terrain_place.lua
--
-- Moves parked ground-object sites (SAM and EWR sites, armour, missile and
-- coastal sites, motorpools) off steep slopes and roads, and SAMs, EWRs,
-- armour and missile sites out of town centres, at mission start.
--
-- Data: dcsRetributionTerrain, written by game/livingworld/terrain.py:
--   sites    = { { name = ..., role = "sam" | "ewr" | "armor" | "site" |
--                  "parked", groups = { group names } }, ... }
--   towns    = { { name, x, y, r }, ... }   (only towns near listed groups)
--   maxSlope = 0.2                          (rise over run, about 11 degrees)
--   searchMax = 1200                        (metres a group may move)
--
-- How: a site is scored by how many of its units (all its groups together)
-- stand on a bad spot (a road, runway or water surface, or a slope steeper
-- than maxSlope), plus a big penalty when a town-avoiding site's centre is
-- inside a town centre. A site with score 0 is left alone. Otherwise all its
-- groups are shifted by the same offset (keeping the layout: radar,
-- launchers and protecting AAA stay together) to the nearest offset,
-- on rings every 60 m out to searchMax, with the lowest score; it is only
-- moved if that is better than where it stands. Like water_relocate.lua it
-- re-adds the group under the same group and unit names with mist.dynAdd, so
-- Retribution's loss tracking is unaffected.
--
-- Runs straight away when the script loads (not on a timer), so it happens
-- before plugins loaded later (Skynet IADS) look the groups up.

TerrainPlace = TerrainPlace or {}

local STEP = 60          -- metres between search rings
local HEADINGS = 12      -- candidate points per ring
local PROBE = 8          -- metres either side of a unit for the slope
local TOWN_PENALTY = 1000

local TOWN_ROLES = { sam = true, ewr = true, armor = true, site = true }

local function log(msg)
    env.info("terrain_place: " .. msg)
end

local function slope_at(x, y)
    local hn = land.getHeight({ x = x + PROBE, y = y })
    local hs = land.getHeight({ x = x - PROBE, y = y })
    local he = land.getHeight({ x = x, y = y + PROBE })
    local hw = land.getHeight({ x = x, y = y - PROBE })
    return math.max(math.abs(hn - hs), math.abs(he - hw)) / (2 * PROBE)
end

-- Why a spot is bad: "road", "runway", "water", "slope", or nil when fine.
function TerrainPlace.spot_problem(x, y, max_slope)
    local s = land.getSurfaceType({ x = x, y = y })
    if s == land.SurfaceType.ROAD then
        return "road"
    elseif s == land.SurfaceType.RUNWAY then
        return "runway"
    elseif s == land.SurfaceType.WATER or s == land.SurfaceType.SHALLOW_WATER then
        return "water"
    end
    if slope_at(x, y) > max_slope then
        return "slope"
    end
    return nil
end

function TerrainPlace.town_at(x, y, towns)
    for _, t in ipairs(towns or {}) do
        local dx, dy = x - t.x, y - t.y
        if dx * dx + dy * dy < t.r * t.r then
            return t
        end
    end
    return nil
end

local function centre(units)
    local sx, sy = 0, 0
    for _, u in ipairs(units) do
        sx, sy = sx + u.x, sy + u.y
    end
    return sx / #units, sy / #units
end

-- Score of the group shifted by (dx, dy): units on a bad spot, plus the town
-- penalty. Also returns the reasons, for the log.
function TerrainPlace.score(units, role, dx, dy, data)
    local bad, why = 0, {}
    for _, u in ipairs(units) do
        local p = TerrainPlace.spot_problem(u.x + dx, u.y + dy, data.maxSlope or 0.2)
        if p then
            bad = bad + 1
            why[p] = (why[p] or 0) + 1
        end
    end
    if TOWN_ROLES[role] then
        local cx, cy = centre(units)
        local town = TerrainPlace.town_at(cx + dx, cy + dy, data.towns)
        if town then
            bad = bad + TOWN_PENALTY
            why["town " .. town.name] = 1
        end
    end
    return bad, why
end

local function describe(why)
    local parts = {}
    for k, n in pairs(why) do
        parts[#parts + 1] = (n > 1 and (n .. " on ") or "") .. k
    end
    table.sort(parts)
    return table.concat(parts, ", ")
end

-- The best offset for a group, or nil when it is fine or nothing is better.
function TerrainPlace.best_offset(units, role, data)
    local now, why = TerrainPlace.score(units, role, 0, 0, data)
    if now == 0 then
        return nil
    end
    local best, best_score = nil, now
    local max = data.searchMax or 1200
    for r = STEP, max, STEP do
        for i = 0, HEADINGS - 1 do
            local a = i * (2 * math.pi / HEADINGS)
            local dx, dy = r * math.cos(a), r * math.sin(a)
            local s = TerrainPlace.score(units, role, dx, dy, data)
            if s < best_score then
                best, best_score = { dx = dx, dy = dy, r = r }, s
                if s == 0 then
                    return best, now, s, why
                end
            end
        end
    end
    return best, now, best_score, why
end

-- Move a site (all its groups by one offset). Returns true if moved.
function TerrainPlace.place_site(site, data)
    local groups, units = {}, {}
    for _, name in ipairs(site.groups or {}) do
        local group = mist.getGroupData(name)
        if group and group.units and #group.units > 0 then
            groups[#groups + 1] = group
            for _, u in ipairs(group.units) do
                units[#units + 1] = u
            end
        end
    end
    if #units == 0 then
        return false
    end
    local offset, before, after, why = TerrainPlace.best_offset(units, site.role, data)
    if not offset then
        if before and before > 0 then
            log(site.name .. ": " .. describe(why) .. ", no better spot within "
                .. (data.searchMax or 1200) .. " m")
        end
        return false
    end
    for _, group in ipairs(groups) do
        for _, u in ipairs(group.units) do
            u.x, u.y = u.x + offset.dx, u.y + offset.dy
        end
        if group.route and group.route.points then
            for _, p in ipairs(group.route.points) do
                p.x, p.y = p.x + offset.dx, p.y + offset.dy
            end
        end
        mist.dynAdd(group)
    end
    log(string.format("moved %s %d m (%s; %d -> %d)", site.name, offset.r,
        describe(why), before, after))
    return true
end

function TerrainPlace.run()
    local data = dcsRetributionTerrain
    if not data or not data.sites then
        return 0
    end
    local moved = 0
    for _, site in ipairs(data.sites) do
        local ok, result = pcall(TerrainPlace.place_site, site, data)
        if not ok then
            env.warning("terrain_place: " .. tostring(site.name) .. ": " .. tostring(result))
        elseif result then
            moved = moved + 1
        end
    end
    log(moved .. " of " .. #data.sites .. " sites moved")
    return moved
end

if not TerrainPlace.no_autorun then
    TerrainPlace.run()
end
