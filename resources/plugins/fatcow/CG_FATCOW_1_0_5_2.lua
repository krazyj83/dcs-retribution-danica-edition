-- FATCOW script by Don Rudi/C. Gurk 
-- © 11/2024
local FATCOW_VERSION = "1.0.5.2"

-- User adaptable values
local FARP_DURATION = 20 * 60							-- how long will the FARP be active, in minutes
local FATCOW_SPAWN_DISTANCE = 10 						-- how far out will the Fatcow spawn, in nm
local nFuel = 5000										-- default how many kilograms of jetfuel and av gas are in the warehouse
local nHellfire = 2										-- default how many Hellfires of each type are in the Warehouse
local nHydra = 38										-- default how many Hydras of each available type are in the Warehouse
local nAPKWS = 7										-- default how many APKWS Hydras are in the Warehouse

-- default values
local FATCOW_TYPE = "CH-47Fbl1" 						-- helo type, for less resources use default AI "CH-47D"
local FARP_COALITION = 2 								-- blue
local FARP_COUNTRY = 2 									-- USA
local heloGroupName = "FATCOW"							-- Group Name
local heloNum = "19"									-- string for the number in the helicopter
local FARP_ERECT_DELAY = 10 							-- how long it takes to erect the farp after landing in seconds
local FATCOW_SOLDIER = "Soldier M4"
local FATCOW_MANPAD = "Soldier stinger"

local FATCOW_RED = "Mi-26"								-- alternatively use "Mi-8MT"
local FATCOW_RED_FUEL_TYPE = "FARP Fuel Depot"
local FATCOW_RED_FUEL_SHAPE = ""
local FATCOW_RED_SOLDIER = "Paratrooper AKS-74"
local FATCOW_RED_MANPAD = "SA-18 Igla-S manpad"
local FATCOW_RED_COUNTRY_ID = country.id.CJTF_RED		-- CJTF Red

local FATCOW_BLUE = "CH-47Fbl1"
local FATCOW_BLUE_FUEL_TYPE = "FARP Fuel Depot"
local FATCOW_BLUE_FUEL_SHAPE = ""
local FATCOW_BLUE_SOLDIER = "Soldier M4 GRG"
local FATCOW_BLUE_MANPAD = "Soldier stinger"
local FATCOW_BLUE_COUNTRY_ID = country.id.CJTF_BLUE		-- CJTF Blue

local spawnPoint

-- Helper function to convert nautical miles to meters
local function nauticalMilesToMeters(nm)
    return nm * 1852
end

-- Function to spawn the helicopter 15 nautical miles from the marker in a random direction
local function spawnHeloAtRandomPoint(markerPoint)
    local randomAngle = math.random() * 2 * math.pi
    local distance = nauticalMilesToMeters(FATCOW_SPAWN_DISTANCE)

    spawnPoint = {
        x = markerPoint.x + distance * math.cos(randomAngle),
        y = markerPoint.y + distance * math.sin(randomAngle)
    }
	
	
	-- Get the ground elevation at the spawn point
	local groundElevation = land.getHeight({x = spawnPoint.x, y = spawnPoint.y})

	-- Define the helo group with adjusted altitude based on ground elevation
	local spawnAltitude = groundElevation + 500 * 0.3048 -- 300 feet to meters above ground level	
    	
	-- Calculate the heading towards the markerPoint
	local deltaX = markerPoint.x - spawnPoint.x
	local deltaY = markerPoint.y - spawnPoint.y
	local headingToMarker = math.atan2(deltaY, deltaX) -- Heading in radians	
		
	-- set helo and assets according to side
	if FARP_COALITION == 1 then
		FATCOW_TYPE = FATCOW_RED
		FATCOW_SOLDIER = FATCOW_RED_SOLDIER
		FATCOW_MANPAD = FATCOW_RED_MANPAD
		FARP_COUNTRY_ID = country.id.CJTF_RED
		FARP_COUNTRY = 81
	elseif FARP_COALITION == 2 then
		FATCOW_TYPE = FATCOW_BLUE
		FATCOW_SOLDIER = FATCOW_BLUE_SOLDIER
		FATCOW_MANPAD = FATCOW_BLUE_MANPAD
		FARP_COUNTRY_ID = country.id.CJTF_BLUE
		FARP_COUNTRY = 82
	end

    -- Define the helo group
    local heloGroupData = {
        visible = false,
        groupId = nil,
        hidden = false,
        units = {
            [1] = {
                type = FATCOW_TYPE,
				onboard_num = "19",
                unitId = nil,
                skill = "High",
                y = spawnPoint.y,
                x = spawnPoint.x,
                name = heloGroupName,
                callsign = {
                  name = heloGroupName .. heloNum,
                  callsignType = 1
                },
                heading = headingToMarker,
                alt = spawnAltitude,
                speed = 80 * 0.514444 -- 80 knots to meters per second
            }
        },
        y = spawnPoint.y,
        x = spawnPoint.x,
        name = heloGroupName,
        task = nil,
        route = {}
    }

    coalition.addGroup(FARP_COUNTRY_ID, Group.Category.HELICOPTER, heloGroupData)
    trigger.action.outText(heloGroupName .. " helicopter spawned at random location.", 10)
end

-- Function to set FATCOW_EXPIRED flag to true
function setFATCOWExpiredFlag()
    trigger.action.setUserFlag("FATCOW_EXPIRED", true)
    trigger.action.outText("FARP duration expired.", 10)
	despawnFARP()
end

-- This function will be called whenever a new marker is added on the F10 map
function onMapMarkerChange(event)
    if event.text == nil or event.text == "" then
        return
    end
	
	-- Format the marker text: make it uppercase and remove spaces
    local markerText = string.gsub(string.upper(event.text), "%s", "")
	FARP_COALITION = event.coalition 
    
    if markerText == "##FATCOW" then
        -- Get the coordinates of the marker
        local point = { x = event.pos.x, y = event.pos.z }

        -- Spawn the helo at a random point 15 nautical miles from the marker
        spawnHeloAtRandomPoint(point)

        -- Find the helo group by name
        timer.scheduleFunction(function()
            local heloGroup = Group.getByName(heloGroupName)
            if heloGroup and heloGroup:isExist() then
                --trigger.action.outText("FATCOW helicopter found. Preparing to move to marker.", 10)
                local controller = heloGroup:getController()
                if controller then
                    -- Create waypoints for the helicopter mission
                    local halfwayPoint = {
                        x = (heloGroup:getUnit(1):getPoint().x + point.x) / 2,
                        y = (heloGroup:getUnit(1):getPoint().z + point.y) / 2
                    }

                    local mission = {
                        id = 'Mission',
                        params = {
                            route = {
                                points = {
                                    [1] = {
                                        action = "Turning Point",
                                        x = halfwayPoint.x,
                                        y = halfwayPoint.y,
                                        alt = 500 * 0.3048, -- 500 feet to meters
										alt_Type = "RADIO",
                                        speed = 80 * 0.514444 -- 80 knots to meters per second
                                    },
                                    [2] = {
                                        action = "Turning Point",
                                        x = point.x,
                                        y = point.y,
                                        alt = 0, -- Altitude set to ground level for landing
                                        speed = 40 * 0.514444 -- Slow down for landing
                                    }
                                }
                            }
                        }
                    }

                    -- Assign mission to the helicopter
                    controller:setTask(mission)

                    trigger.action.outText(heloGroupName .. heloNum .. " is " .. FATCOW_SPAWN_DISTANCE .. " miles out. Moving to waypoint and preparing to land at marker location.", 10)

                    -- Add advanced waypoint action to land at the marked point
                    local landTask = {
                        id = 'Land',
                        params = {
                            point = {
                                x = point.x,
                                y = point.y
                            },
                            duration = FARP_DURATION,
							combatLandingFlag = true
                        }
                    }
                    controller:pushTask(landTask)

                    -- Monitor landing
                    timer.scheduleFunction(function()
                        if heloGroup and heloGroup:isExist() then
                            local unit = heloGroup:getUnit(1)
                            if unit then
                                local velocity = unit:getVelocity()
                                local altitude = land.getHeight({ x = unit:getPoint().x, y = unit:getPoint().z })
                                local altitudeAGL = unit:getPoint().y - altitude
                                if velocity and math.abs(velocity.y) < 2 and altitudeAGL < 5 then
                                    -- After ensuring it has landed, apply the delay
                                    timer.scheduleFunction(function()
                                        spawnFARP(heloGroupName)
										trigger.action.outText(heloGroupName .. heloNum .. " has landed. FARP will be active for ".. FARP_DURATION/60 .. " minutes.", 10)
                                    end, {}, timer.getTime() + FARP_ERECT_DELAY)
									  -- Set a dedicated function to set FATCOW_EXPIRED to true after FARP_DURATION
										timer.scheduleFunction(setFATCOWExpiredFlag, {}, timer.getTime() + FARP_DURATION)
                                else
                                    -- Keep checking until the helicopter has actually landed
                                    return timer.getTime() + 5
                                end
                            end
                        end
                    end, {}, timer.getTime() + 10) 
                else
                    trigger.action.outText("Unable to control FATCOW. No valid controller found.", 10)
                end
            else
                trigger.action.outText("Unable to find the FATCOW helicopter group.", 10)
            end
        end, {}, timer.getTime() + 1)
    end
end

function getHelicopterPosition(heliName)
    local heli = Unit.getByName(heliName)
    if heli and heli:isExist() then
        local position = heli:getPosition()
        local heading = math.atan2(position.x.z, position.x.x)
        return heli:getPoint(), heading
    end
    return nil, nil
end

-- Fill FARP Warehouse
local function FARP_FILL()
		Airbase.getByName("FATCOW_FARP"):getWarehouse():setLiquidAmount(0, nFuel)								-- 5000 Liters Jetfuel
		Airbase.getByName("FATCOW_FARP"):getWarehouse():setLiquidAmount(1, nFuel)								-- 5000 Liters Av Gas
		
		--optional armament section
		
		-- Blue
		if FARP_COUNTRY == 82 then
		
			--Apache
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.missiles.{AGM_114L}", nHellfire)		-- AGM-114L radar Hellfires
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,4,8,59}, nHellfire)						-- AGM-114L radar Hellfires
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,168}, 38)							-- 38 Hydra-70 M151
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,169}, 38)							-- 38 Hydra-70 M156
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,6,10,2}, 600)							-- 200 rounds 30mm (Apache)
			
			--Kiowa
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.missiles.AGM_114K", nHellfire)		-- AGM-114L radar Hellfires
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,4,8,39}, nHellfire)						-- two AGM-114K laser Hellfires
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,147}, nHydra)						-- Hydra-70 M151
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,148}, nHydra)						-- Hydra-70 M156
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.missiles.AGR_20A", nAPKWS)			-- Hydra-70 APKWS
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,1,2,446},4)								-- four FIM-92
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.OH58D_M3P_L500", 1)		-- one M3P 500 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.OH58D_M3P_L400", 1)		-- one M3P 400 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.OH58D_M3P_L300", 1)		-- one M3P 300 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.OH58D_M3P_L200", 1)		-- one M3P 200 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.OH58D_M3P_L100", 1)		-- one M3P 100 rounds
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_Red_Smoke_Grenade", 4)	-- four Smoke Grenade Red
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_Blue_Smoke_Grenade", 4)	-- four Smoke Grenade Blue
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_Green_Smoke_Grenade", 4)	-- four Smoke Grenade Green
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_Violet_Smoke_Grenade", 4)-- four Smoke Grenade Violet
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_Yellow_Smoke_Grenade", 4)-- four Smoke Grenade Yellow
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.bombs.OH58D_White_Smoke_Grenade", 4)	-- four Smoke Grenade White
			
			--Chinook
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2476}, 1)	-- M60 port
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2477}, 1)	-- M60 starboard
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2478}, 1)	-- M60 aft
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2479}, 1)	-- M240 port
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2480}, 1)	-- M240 starboard
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2481}, 1)	-- M240 aft
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2482}, 1)	-- M134 port
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2483}, 1)	-- M134 starboard
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,2484}, 1)	-- M3M aft
			
			--Huey
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,160}, 1)	-- M134 port pylon
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,161}, 1)	-- M134 starboard pylon
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,174}, 1)	-- M134 port door
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,175}, 1)	-- M134 starboard door
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,176}, 1)	-- M60 port door
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,177}, 1)	-- M60 starboard door
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,164}, 14)	-- 14 Hydra-70 M151
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,165}, 14)	-- 14 Hydra-70 M156
			
			--Gazelle
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.missiles.HOT3_MBDA", 4)			-- four HOT3 missiles
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,15,46,1767}, 1)							-- GIAT SAPHEI
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.GIAT_M621_HE", 1)		-- GIAT HE
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.FN_HMP400_100", 1)		-- one gunpod 100 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.FN_HMP400_200", 1)		-- one gunpod 200 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.gunmounts.FN_HMP400", 1)			-- one gunpod 400 rounds
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.nurs.TELSON8_SNEBT251", 8)			-- 68mm 251 HE
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.nurs.LAU_SNEB68G", 8)				-- 68mm 251 HEAT
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.nurs.TELSON8_SNEBT256", 8)			-- 68mm 256 HE/Frag
			--Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem("weapons.nurs.TELSON8_SNEBT257", 8)			-- 68mm 257 HE/Frag large
		end
		
		-- Red
		if FARP_COUNTRY == 81 then
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,4,8,48}, 4)		-- four 9M114 Shturm
			Airbase.getByName("FATCOW_FARP"):getWarehouse():setItem({4,7,33,150}, 40)	-- 40 S-8 rockets
		end
		
	return nil
end

-- Function to spawn the FARP and associated objects
function spawnFARP(heliName)
    local heliPos, heliHeading = getHelicopterPosition(heliName)
    if heliPos and heliHeading then
        -- Spawn Invisible FARP 100m aft of helicopter
        local farpX = heliPos.x - 100 * math.cos(heliHeading)
        local farpZ = heliPos.z - 100 * math.sin(heliHeading)
		
		-- Calculate position for APFC Fuel 50m aft of helicopter
        local apfcFuelX = heliPos.x - 35 * math.cos(heliHeading)
        local apfcFuelZ = heliPos.z - 35 * math.sin(heliHeading)
		
		-- Calculate position for Fuel Truck 30m left of helicopter
        local fuelX = apfcFuelX - 30 * math.sin(heliHeading)
        local fuelZ = apfcFuelZ + 30 * math.cos(heliHeading)
		
		-- Calculate position for Ammo 30m left of helicopter
        --local ammoX = fuelX - 10 * math.sin(heliHeading)
        --local ammoZ = fuelZ + 10 * math.cos(heliHeading)
		
		-- Calculate position for Humvee as FARP command vehicle
        --local humveeX = heliPos.x + 20 * math.cos(heliHeading)
        --local humveeZ = heliPos.z - 20 * math.sin(heliHeading)

		-- FARP Data
		local farpGroupData = {
            visible = false,
            groupId = nil,
            hidden = false,
            units = {
                [1] = {
                    category = "Heliports",
					type = "Invisible FARP",
					shape_name = "invisiblefarp",
					--type = "FARP_T",
					--shape_name = "FARP_T",
                    name = "FATCOW_FARP",
                    x = farpX,
                    y = farpZ,
                    heading = heliHeading                    
                }--[[,
				[2] = {
					category = "Ground Units",
					type = "M978 HEMTT Tanker",
					name = "FATCOW_FUEL",
					x = fuelX,
					y = fuelZ,
					heading = heliHeading
				},
				[3] = {
					category = "Ground Units",
					type = "M 818",
					name = "FATCOW_AMMO",
					x = ammoX,
					y = ammoZ,
					heading = heliHeading
				},
				[4] = {
					category = "Ground Units",
					type = "Hummer",
					name = "FATCOW_COMMAND",
					x = humveeX,
					y = humveeZ,
					heading = heliHeading + 10
				}]]--
            },
            name = "FATCOW_FARP_GROUP",
            task = nil
        }
        coalition.addGroup(FARP_COUNTRY_ID, -1, farpGroupData)
		
		 -- Get MGRS coordinates of the FARP and display message
        local mgrsCoord = coord.LLtoMGRS(coord.LOtoLL({ lon = farpX, lat = farpZ }))
        local mgrsString = mgrsCoord.UTMZone .. ' ' .. mgrsCoord.MGRSDigraph .. ' ' .. math.floor(mgrsCoord.Easting / 10) .. ' ' .. math.floor(mgrsCoord.Northing / 10)
        trigger.action.outText("FARP deployed at MGRS: " .. mgrsString, 30)
		
		-- Static objects
		
		 -- Spawn Fuel (FARP Fuel Depot)
        local fuelTruck = {
            category = "Fortifications",
            type = "FARP Fuel Depot",
            name = "FATCOW_FUEL",
            x = fuelX,
            y = fuelZ,
            heading = heliHeading
        }
        coalition.addStaticObject(FARP_COUNTRY_ID, fuelTruck)
		
		-- Spawn APFC Fuel 
        local apfcFuel = {
            category = "Fortifications",
            type = "APFC fuel",
            name = "FATCOW_APFC_FUEL",
            x = apfcFuelX,
            y = apfcFuelZ,
            heading = heliHeading
        }
        coalition.addStaticObject(FARP_COUNTRY_ID, apfcFuel)
		 
        -- Calculate position for Fire Extinguisher 70m aft of helicopter
        local extinguisherX = heliPos.x - 70 * math.cos(heliHeading)
        local extinguisherZ = heliPos.z - 70 * math.sin(heliHeading)

        -- Spawn Fire Extinguisher
        local fireExtinguisher = {
            category = "Fortifications",
            shape_name = "M92_FireExtinguisher01",
            type = "FireExtinguisher01",
            name = "FATCOW_FIRE_EXTINGUISHER",
            x = extinguisherX,
            y = extinguisherZ,
            heading = heliHeading
        }
        coalition.addStaticObject(FARP_COUNTRY_ID, fireExtinguisher)

       --Calculate generator and hose
		local hoseX = heliPos.x - 50 * math.cos(heliHeading)
        local hoseZ = heliPos.z - 50 * math.sin(heliHeading)

        -- Spawn generator and hose
        local hose1 = {
            category = "Fortifications",
            shape_name = "M92_M32-10C_01",
            type = "M32-10C_01",
            name = "FATCOW_HOSE1",
            x = hoseX,
            y = hoseZ,
            heading = heliHeading
        }
        coalition.addStaticObject(FARP_COUNTRY_ID, hose1)
		
		-- Spawn Infantry next to Fire Extinguisher (left and right)
        local personnelHeading = (heliHeading + math.pi) % (2 * math.pi)  -- Facing 180 degrees away from helicopter
        local personnelPositions = {
            { x = extinguisherX - 2 * math.cos(heliHeading + math.pi / 2), z = extinguisherZ - 2 * math.sin(heliHeading + math.pi / 2) },  -- 2 meters left of extinguisher
            { x = extinguisherX + 2 * math.cos(heliHeading + math.pi / 2), z = extinguisherZ + 2 * math.sin(heliHeading + math.pi / 2) }   -- 2 meters right of extinguisher
        }

        for i, pos in ipairs(personnelPositions) do
            local personnel = {
                category = "Infantry",
                type = FATCOW_SOLDIER,
                name = "FATCOW_INFANTRY_PERSONNEL_" .. i,
                x = pos.x,
                y = pos.z,
                heading = personnelHeading
            }
            coalition.addStaticObject(FARP_COUNTRY_ID, personnel)
        end
		-- Define the infantry group data with 6 infantry and 1 MANPAD
		local infantryGroupData = {
			visible = true,
			name = "FATCOW_INFANTRY_GROUP",
			country = FARP_COUNTRY_ID,
			category = Group.Category.GROUND,
			task = "Ground Nothing",
			units = {
				[1] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x - 20,
					y = heliPos.z - 5,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_1"
				},
				[2] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x - 20,
					y = heliPos.z + 5,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_2"
				},
				[3] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x + 5,
					y = heliPos.z + 20,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_3"
				},
				[4] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x - 5,
					y = heliPos.z + 20,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_4"
				},
				[5] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x + 20,
					y = heliPos.z + 10,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_5"
				},
				[6] = {
					type = FATCOW_SOLDIER,
					x = heliPos.x + 20,
					y = heliPos.z - 10,
					heading = heliHeading,
					name = "FATCOW_INFANTRY_6"
				},
				[7] = {
					type = FATCOW_MANPAD,
					x = heliPos.x + 50 * math.cos(heliHeading),
					y = heliPos.z + 50 * math.sin(heliHeading),
					heading = heliHeading,
					name = "FATCOW_INFANTRY_7"
				}
			}
		}

		-- Spawn the infantry group using coalition.addGroup
		coalition.addGroup(FARP_COUNTRY_ID, Group.Category.GROUND, infantryGroupData)

		-- fill FARP Warehouse 5 seconds after spawn
		timer.scheduleFunction(FARP_FILL, {}, timer.getTime() + 5)
    else
        trigger.action.outText("FATCOW helicopter not found!", 10)
    end
end

-- Function to despawn the FARP and all associated objects
function despawnFARP()
    local objectNames = { "FATCOW_FARP", "FATCOW_FIRE_EXTINGUISHER", "FATCOW_APFC_FUEL", "FATCOW_HOSE1", "FATCOW_FUEL", "FATCOW_INFANTRY_GROUP" }
   
    for i = 1, 2 do
        table.insert(objectNames, "FATCOW_INFANTRY_PERSONNEL_" .. i)
    end
    
    for _, name in ipairs(objectNames) do
        local obj = StaticObject.getByName(name)
        if obj and obj:isExist() then
            obj:destroy()
        end
    end
    trigger.action.outText("FATCOW FARP deactivated!", 10)
	
	 local heloGroup = Group.getByName(heloGroupName)
	if heloGroup and heloGroup:isExist() then
		local controller = heloGroup:getController()
		if controller then
			local takeOffTask = {
				id = 'Mission',
				params = {
					route = {
						points = {
							[1] = {
								action = "Turning Point",
								x = spawnPoint.x,
								y = spawnPoint.y,
								alt = 1000 * 0.3048, -- 1000 feet to meters
								speed = 80 * 0.514444 -- 80 knots to meters per second
							}
						}
					}
				}
			}
			controller:setTask(takeOffTask)
            -- Schedule deactivation of the helicopter after reaching the spawn point
            timer.scheduleFunction(function()
                if heloGroup and heloGroup:isExist() then
                    heloGroup:destroy()
                    trigger.action.outText(heloGroupName .. heloNum .. " has returned to the spawn point and deactivated.", 10)
                end
            end, {}, timer.getTime() + 300)
		end
	end
end

-- Add an event handler to listen for new map markers
-- pcall wrapper prevents CTLD or other scripts from breaking this handler
world.addEventHandler({
    onEvent = function(self, event)
        local ok, err = pcall(function()
            if event.id == world.event.S_EVENT_MARK_CHANGE then
                onMapMarkerChange(event)
            end
        end)
        if not ok then
            trigger.action.outText("FATCOW event handler error: " .. tostring(err), 10)
        end
    end
})

-- loading message
trigger.action.outText("CG FATCOW script version " .. FATCOW_VERSION .. " loaded. Use ##FATCOW marker (CTLD-compatible).", 5)