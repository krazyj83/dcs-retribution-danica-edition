--[[
  resources/plugins/retribution_logistics.lua

  DCS Retribution — Logistics Delivery Script
  Runs inside the generated .miz mission.

  What this script does:
    1. Reads the list of active transfers injected by the Python mission
       generator into the mission's "do script" trigger.
    2. Monitors helicopter/transport aircraft for arrival at drop zones
       (using MIST zone detection).
    3. When an aircraft enters a RETRIBUTION_DZ_* trigger zone, marks
       the delivery as complete and logs a logistics_event to the
       retribution_state.json export.
    4. Handles aircraft loss (unit dead before reaching the zone).

  Dependencies:
    - MIST (already embedded in all Retribution missions)
    - retribution_export.lua (the existing state exporter)

  Zone naming convention (must match Python DropZone.trigger_zone_name):
    RETRIBUTION_DZ_TROOP_{NAME}   — troop drop zones
    RETRIBUTION_DZ_CARGO_{NAME}   — cargo drop zones
]]

RETRIBUTION_LOGISTICS = {}
RETRIBUTION_LOGISTICS.version = "1.0.0"

-- Transfer table: injected by Python mission generator.
-- Format: { transfer_id, unit_name, dz_name, category, quantity }
-- Python writes this as a Lua table literal in the mission triggers.
RETRIBUTION_LOGISTICS.transfers = RETRIBUTION_LOGISTICS_TRANSFERS or {}

-- Event log: written to state.json on mission end.
RETRIBUTION_LOGISTICS.events = {}

-- Track which unit names are still alive.
RETRIBUTION_LOGISTICS.alive_units = {}

--------------------------------------------------------------------------------
-- Initialise
--------------------------------------------------------------------------------
function RETRIBUTION_LOGISTICS.init()
  env.info("[RETRIBUTION_LOGISTICS] Initialising v" .. RETRIBUTION_LOGISTICS.version)

  -- Register unit names from transfer table
  for _, transfer in ipairs(RETRIBUTION_LOGISTICS.transfers) do
    RETRIBUTION_LOGISTICS.alive_units[transfer.unit_name] = true
    env.info(
      "[RETRIBUTION_LOGISTICS] Tracking unit '" .. transfer.unit_name ..
      "' for transfer " .. transfer.transfer_id
    )
  end

  -- Set up zone monitoring using MIST scheduler
  mist.scheduleFunction(RETRIBUTION_LOGISTICS.check_zones, {}, timer.getTime() + 5, 10)

  -- Listen for unit deaths
  RETRIBUTION_LOGISTICS.death_handler = mist.addEventHandler(
    RETRIBUTION_LOGISTICS.on_event
  )

  env.info("[RETRIBUTION_LOGISTICS] Init complete. Tracking " ..
           #RETRIBUTION_LOGISTICS.transfers .. " transfers.")
end

--------------------------------------------------------------------------------
-- Zone check (runs every 10 seconds)
--------------------------------------------------------------------------------
function RETRIBUTION_LOGISTICS.check_zones()
  for _, transfer in ipairs(RETRIBUTION_LOGISTICS.transfers) do
    -- Skip already-resolved transfers
    if not transfer.resolved then
      local unit = Unit.getByName(transfer.unit_name)
      if unit and unit:isActive() then
        local pos = unit:getPoint()
        -- Check if unit is inside the designated drop zone
        if mist.pointInZone(pos, transfer.dz_name) then
          RETRIBUTION_LOGISTICS.deliver(transfer, unit)
        end
      end
    end
  end
end

--------------------------------------------------------------------------------
-- Deliver: unit has reached the drop zone
--------------------------------------------------------------------------------
function RETRIBUTION_LOGISTICS.deliver(transfer, unit)
  -- Calculate actual quantity based on fuel state (proxy for partial delivery)
  -- A full aircraft delivers 100%; damaged aircraft delivers proportionally.
  local life_pct = 1.0
  if unit.getLife and unit:getLife() and unit:getLife0() then
    life_pct = math.min(1.0, unit:getLife() / unit:getLife0())
  end
  local actual = math.floor(transfer.quantity * math.min(life_pct + 0.5, 1.0))

  transfer.resolved = true

  local event = {
    transfer_id = transfer.transfer_id,
    dz_name     = transfer.dz_name,
    category    = transfer.category,
    planned     = transfer.quantity,
    delivered   = actual,
    success     = true,
    unit_name   = transfer.unit_name,
    time        = timer.getAbsTime(),
  }
  table.insert(RETRIBUTION_LOGISTICS.events, event)

  env.info(string.format(
    "[RETRIBUTION_LOGISTICS] DELIVERED: transfer=%s unit=%s dz=%s qty=%d/%d",
    transfer.transfer_id, transfer.unit_name, transfer.dz_name, actual, transfer.quantity
  ))

  -- Trigger a green smoke at the drop zone to give visual feedback in DCS
  local zone = mist.DBs.zonesByName[transfer.dz_name]
  if zone then
    trigger.action.smoke(zone.point, trigger.smokeColor.Green)
  end
end

--------------------------------------------------------------------------------
-- Death handler: unit was destroyed before delivery
--------------------------------------------------------------------------------
function RETRIBUTION_LOGISTICS.on_event(event)
  if event.id == world.event.S_EVENT_DEAD then
    local unit = event.initiator
    if unit and Unit.getName then
      local name = Unit.getName(unit)
      if RETRIBUTION_LOGISTICS.alive_units[name] then
        -- Find the matching transfer and mark it failed
        for _, transfer in ipairs(RETRIBUTION_LOGISTICS.transfers) do
          if transfer.unit_name == name and not transfer.resolved then
            transfer.resolved = true
            local fail_event = {
              transfer_id = transfer.transfer_id,
              dz_name     = transfer.dz_name,
              category    = transfer.category,
              planned     = transfer.quantity,
              delivered   = 0,
              success     = false,
              unit_name   = name,
              time        = timer.getAbsTime(),
            }
            table.insert(RETRIBUTION_LOGISTICS.events, fail_event)
            env.info(string.format(
              "[RETRIBUTION_LOGISTICS] FAILED: transfer=%s unit=%s (unit dead)",
              transfer.transfer_id, name
            ))
            -- Red smoke at intended DZ for visual feedback
            local zone = mist.DBs.zonesByName[transfer.dz_name]
            if zone then
              trigger.action.smoke(zone.point, trigger.smokeColor.Red)
            end
          end
        end
        RETRIBUTION_LOGISTICS.alive_units[name] = nil
      end
    end
  end
end

--------------------------------------------------------------------------------
-- Export: append logistics events to the retribution state export
-- Called by retribution_export.lua at mission end.
--------------------------------------------------------------------------------
function RETRIBUTION_LOGISTICS.export_events()
  return RETRIBUTION_LOGISTICS.events
end

--------------------------------------------------------------------------------
-- Bootstrap
--------------------------------------------------------------------------------
mist.scheduleFunction(RETRIBUTION_LOGISTICS.init, {}, timer.getTime() + 1)

env.info("[RETRIBUTION_LOGISTICS] Script loaded.")
