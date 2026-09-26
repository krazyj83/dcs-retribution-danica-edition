Weapon cargo transfers
(cargo planned in the mission planner, kneeboard load sheet, in-mission F10 cargo orders)
Upload AFTER "Supply transport tiers v2". Commit everything to dev, overwriting files.
The two .png files are previews only - do not upload them.

PLANNING (Retribution)
  1. Click the destination base (friendly airfield or FOB/FARP) -> New package.
  2. Add Flight -> LOGISTIC -> transport squadron -> client slot.
  3. Flight -> "Cargo" tab: pick-up base, drop zone, fuel (100/50/25 %), load weapons.
     Weight bar and route update live; loads that don't fit are refused.
  Deleting the flight/package puts the cargo back in stock.

IN THE MISSION (DCS)
  - Planned cargo waits as crates next to the aircraft (or at the pick-up base).
  - Kneeboard "Load Sheet": route, weights, cargo, crate positions.
  - More trips: land at any friendly base -> F10 > Cargo > Order at <base>
      > category > weapon > quantity (1/2/4/10/20).
    The crate appears 25 m right of a helicopter / 35 m behind a plane, with its
    real mass. Refused if the base doesn't have it or it's too heavy at your fuel.
    F10 > Cargo > Cancel last order  (only if the crate hasn't been moved)
    F10 > Cargo > Cargo status       (where each of your crates is)

AFTER THE MISSION (settlement, per crate)
  on the ground at a friendly base  -> delivered to THAT base
  destroyed                         -> lost
  anywhere else / still in aircraft -> planned cargo back to its base; ordered
                                       cargo never left its base
                                       (lost if the flight was shot down)
  "At a base" = within 2.5 km of an airfield, 750 m of a FARP/FOB, or inside
  one of the base's drop zones. Crate still hanging (>3 m up) = not delivered.
  Missions from before this update fall back to "delivered if the flight survives".

NEW FILES
  game/logistics/cargo.py, flight_cargo.py, crate_delivery.py
  game/missiongenerator/transfercargogenerator.py
  qt_ui/windows/mission/flight/cargo/QFlightCargoTab.py
  resources/logistics/cargo_aircraft.yaml
  resources/plugins/base/retribution_cargo.lua   (mission script, loaded with the base plugin)
  tests/test_weapon_cargo.py, tests/test_retribution_cargo_lua.py (skipped without Lua 5.1)
