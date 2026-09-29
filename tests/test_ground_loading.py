"""Player aircraft loading from the base's stores (logistics/ground_loading.py)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from dcs.weapons_data import Weapons

from game.ato.starttype import StartType
from game.logistics import LogisticsManager, WeaponInventory, new_base_warehouse
from game.logistics.ground_loading import (
    applies_to,
    configure_airports,
    script_data,
)
from game.logistics.weapon_use import stores_for_ammo
from game.theater.player import Player

BASE = Path("resources/plugins/base")
LUA = shutil.which("lua5.1") or shutil.which("luajit")

AMRAAM: dict[str, Any] = dict(Weapons.AIM_120C_AMRAAM___Active_Radar_AAM)
RACK: dict[str, Any] = dict(Weapons.BRU_33_with_2_x_GBU_12___500lb_Laser_Guided_Bomb)
GBU12: dict[str, Any] = dict(Weapons.GBU_12)


def _airfield(side: Player = Player.BLUE) -> Any:
    from game.theater.controlpoint import Airfield

    class _Field(Airfield):
        captured = None  # type: ignore[assignment]

    cp: Any = _Field.__new__(_Field)
    cp.id = uuid4()
    cp.name = "Kutaisi"
    cp.captured = side
    cp.airport = SimpleNamespace(name="Kutaisi")
    return cp


def _game(*cps: Any, on: bool = True) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(logistics_players_load_on_ground=on),
        logistics=LogisticsManager(),
        theater=SimpleNamespace(controlpoints=list(cps)),
    )


def _flight(cp: Any, start: StartType = StartType.COLD) -> Any:
    return SimpleNamespace(departure=cp, start_type=start)


PLAYER, AI = SimpleNamespace(is_player=True), SimpleNamespace(is_player=False)


def test_only_players_on_the_ground_at_friendly_airfields() -> None:
    kutaisi = _airfield()
    game = _game(kutaisi)
    assert applies_to(game, _flight(kutaisi), PLAYER)
    assert not applies_to(game, _flight(kutaisi), AI)
    assert not applies_to(game, _flight(kutaisi, StartType.IN_FLIGHT), PLAYER)
    fob = SimpleNamespace(captured=Player.BLUE)  # not an airfield
    assert not applies_to(game, _flight(fob), PLAYER)
    assert not applies_to(_game(kutaisi, on=False), _flight(kutaisi), PLAYER)


def _stocked(game: Any, cp: Any) -> None:
    game.logistics.add_warehouse(new_base_warehouse(cp))
    inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)
    inv.add_item(AMRAAM["clsid"], AMRAAM["name"], "x", quantity=12)
    inv.add_item(RACK["clsid"], RACK["name"], "x", quantity=5)
    inv.add_item(GBU12["clsid"], GBU12["name"], "x", quantity=0)
    game.logistics.set_weapon_inventory(inv)


def test_script_data_and_dcs_warehouse_limits() -> None:
    kutaisi = _airfield()
    game = _game(kutaisi)
    _stocked(game, kutaisi)

    data = script_data(game)
    (base,) = data["bases"]
    assert base["airbase"] == "Kutaisi" and base["fuel_kg"] == 2000 * 200
    stores = {s["key"].split("|")[0]: s for s in base["stores"]}
    assert stores["AIM120CAMRAAMACTIVERADARAAM"]["count"] == 12
    assert stores["BRU33WITH2XGBU12500LBLASERGUIDEDBOMB"]["per_store"] == 2
    assert len(stores) == 2  # the empty GBU-12 store is left out

    airport = SimpleNamespace(
        unlimited_fuel=True, unlimited_munitions=True, jet_init=100
    )
    mission = SimpleNamespace(terrain=SimpleNamespace(airports={"Kutaisi": airport}))
    configure_airports(game, mission)
    assert airport.unlimited_fuel is False and airport.unlimited_munitions is False
    assert airport.jet_init == 400.0  # tons


def test_ground_loaded_aircraft_are_charged_from_the_base_stores() -> None:
    kutaisi = _airfield()
    game = _game(kutaisi)
    _stocked(game, kutaisi)
    inv = game.logistics.get_weapon_inventory(kutaisi.id)

    used = stores_for_ammo(inv, {"AIM_120C": 2, "GBU_12": 3, "M61_20_HE": 200})

    # GBU-12s come from the single-bomb store first (smallest rack).
    assert used == {AMRAAM["clsid"]: 2, GBU12["clsid"]: 3}


MOCK = r"""
local handlers = {}
local scheduled = {}
timer = {getTime = function() return 0 end,
         scheduleFunction = function(f, a, t) table.insert(scheduled, f) end}
env = {info = function() end, mission = {coalition = {}}}
mist = {
  Logger = {new = function() return {info = function() end, error = function() end} end},
  addEventHandler = function(f) table.insert(handlers, f) end,
  scheduleFunction = function() end,
  getHeading = function() return 0 end,
}
world = {event = {S_EVENT_SHOT = 1, S_EVENT_TAKEOFF = 3, S_EVENT_LAND = 4,
  S_EVENT_CRASH = 5, S_EVENT_EJECTION = 6, S_EVENT_DEAD = 8, S_EVENT_PILOT_DEAD = 9,
  S_EVENT_MISSION_END = 12, S_EVENT_KILL = 29, S_EVENT_UNIT_LOST = 30}}
trigger = {action = {outText = function() end}}
AI = {Option = {Air = {val = {ROE = {}}}}}
set_items, liquids = {}, {}
Warehouse = {getResourceMap = function() return {
  ["weapons.missiles.AIM_120C"] = {4, 4, 7, 106},
  ["weapons.bombs.GBU_12"] = {4, 5, 36, 38},
  ["weapons.missiles.AIM_9X"] = {4, 4, 7, 136},
  ["LAU-61"] = {1, 2, 3, 4},
} end}
local wh = {setItem = function(self, n, c) set_items[n] = c end,
            setLiquidAmount = function(self, t, a) liquids[t] = a end}
Airbase = {getByName = function(n) return {getWarehouse = function() return wh end} end}
ammo = {}
alive = {}
function unit(name)
  return {getName = function() return name end,
          getPlayerName = function() return "Morten" end,
          isExist = function() return alive[name] ~= false end,
          getAmmo = function() return ammo[name] end,
          getPosition = function() return {p = {x = 0, y = 0, z = 0}} end,
          getTypeName = function() return "F-16C_50" end}
end
Unit = {getByName = function(n) return unit(n) end}
function fire(id, name)
  for _, h in ipairs(handlers) do h({id = id, initiator = unit(name)}) end
end
function run_scheduled() for _, f in ipairs(scheduled) do f() end end
local function a(t, n) return {count = n, desc = {typeName = t}} end
function loaded(name, amraams, gbus)
  ammo[name] = {a("weapons.missiles.AIM_120C", amraams), a("GBU_12", gbus)}
end
"""

SCENARIO = r"""
dcsRetributionWarehouses = {unmatched = 500, bases = {{airbase = "Kutaisi",
  fuel_kg = 400000, stores = {
    {key = "AIM120CAMRAAMACTIVERADARAAM|AIM120CAMRAAMACTIVERADARAAM", per_store = 1, count = 12},
    {key = "BRU33WITH2XGBU12500LBLASERGUIDEDBOMB|X", per_store = 2, count = 5},
  }}}}
retribution_setup_warehouses()
loaded("Viper 1-1", 4, 2); fire(world.event.S_EVENT_TAKEOFF, "Viper 1-1")
loaded("Viper 1-1", 2, 0); fire(world.event.S_EVENT_LAND, "Viper 1-1")
loaded("Viper 1-2", 4, 2); fire(world.event.S_EVENT_TAKEOFF, "Viper 1-2")
fire(world.event.S_EVENT_CRASH, "Viper 1-2")
loaded("Viper 1-3", 2, 0); fire(world.event.S_EVENT_TAKEOFF, "Viper 1-3")
loaded("Viper 1-3", 1, 0)
write_state()
local f = io.open(os.getenv("RETRIBUTION_EXPORT_DIR") .. "warehouses.json", "w")
f:write(json:encode({items = set_items, fuel = liquids[0]}))
f:close()
"""


@pytest.mark.skipif(LUA is None, reason="lua5.1 not installed")
def test_mission_script_stocks_warehouses_and_counts_player_loads(
    tmp_path: Path,
) -> None:
    script = "\n".join(
        [
            MOCK,
            f'os.getenv = function(k) if k == "RETRIBUTION_EXPORT_DIR" then '
            f'return "{tmp_path.as_posix()}/" end return nil end',
            (BASE / "json.lua").read_text(encoding="utf-8"),
            (BASE / "dcs_retribution.lua").read_text(encoding="utf-8"),
            SCENARIO,
        ]
    )
    runner = tmp_path / "run.lua"
    runner.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [str(LUA), str(runner)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr

    wh = json.loads((tmp_path / "warehouses.json").read_text(encoding="utf-8"))
    assert wh["items"] == {
        "weapons.missiles.AIM_120C": 12,
        "weapons.bombs.GBU_12": 10,  # 5 racks of 2
        "weapons.missiles.AIM_9X": 500,  # no store: still loadable
    }
    assert wh["fuel"] == 400000

    (state_file,) = [p for p in tmp_path.glob("*state.json")]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["player_ammo_used"] == {
        "Viper 1-1": {"AIM_120C": 2, "GBU_12": 2},  # fired, then landed
        "Viper 1-2": {"AIM_120C": 4, "GBU_12": 2},  # lost with everything
        "Viper 1-3": {"AIM_120C": 1},  # still flying at the end
    }
