"""BLUEFOR weapons used in a mission (game/logistics/weapon_use.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from dcs.weapons_data import Weapons

from game.logistics import LogisticsManager, WeaponInventory
from game.logistics.weapon_use import (
    charge_weapon_use,
    stores_used,
    weapon_shortages,
    weapons_per_store,
)
from game.theater.player import Player

AMRAAM: dict[str, Any] = dict(Weapons.AIM_120C_AMRAAM___Active_Radar_AAM)
RACK: dict[str, Any] = dict(Weapons.BRU_33_with_2_x_GBU_12___500lb_Laser_Guided_Bomb)
TANK: dict[str, Any] = dict(Weapons.Fuel_tank_370_gal)


def _w(data: Any) -> Any:
    return SimpleNamespace(clsid=data["clsid"], name=data["name"])


def _loadout(*stores: Any) -> Any:
    return SimpleNamespace(pylons={i + 1: _w(s) for i, s in enumerate(stores)})


F16 = _loadout(AMRAAM, AMRAAM, RACK, TANK)


def test_rack_size_from_the_name() -> None:
    assert weapons_per_store(RACK["name"]) == 2
    assert weapons_per_store("GBU-12 * 2") == 2
    assert weapons_per_store(AMRAAM["name"]) == 1


def test_returning_aircraft_uses_what_it_fired() -> None:
    used, unmatched = stores_used(
        F16, lost=False, shots={"AIM_120C": 1, "GBU_12": 1, "HYDRA_70_M151": 7}
    )
    assert used == {AMRAAM["clsid"]: 1, RACK["clsid"]: 0.5}
    assert unmatched == {"HYDRA_70_M151": 7}


def test_shots_never_exceed_what_was_on_board() -> None:
    used, _ = stores_used(F16, lost=False, shots={"AIM_120C": 5})
    assert used == {AMRAAM["clsid"]: 2}


def test_lost_aircraft_loses_everything_on_its_pylons() -> None:
    used, _ = stores_used(F16, lost=True, shots={})
    assert used == {AMRAAM["clsid"]: 2, RACK["clsid"]: 1, TANK["clsid"]: 1}


def _setup(stock: int = 10) -> Any:
    base = SimpleNamespace(id=uuid4(), name="Larnaca", captured=Player.BLUE)
    logistics = LogisticsManager()
    inv = WeaponInventory(cp_id=base.id, cp_name=base.name)
    for data in (AMRAAM, RACK, TANK):
        inv.add_item(data["clsid"], data["name"], "x", quantity=stock)
    logistics.set_weapon_inventory(inv)
    flight = SimpleNamespace(
        departure=base,
        roster=SimpleNamespace(
            members=[SimpleNamespace(loadout=F16), SimpleNamespace(loadout=F16)]
        ),
    )
    pilots = [object(), object()]
    unit_map = SimpleNamespace(
        aircraft={
            "Viper 1-1": SimpleNamespace(flight=flight, pilot=pilots[0]),
            "Viper 1-2": SimpleNamespace(flight=flight, pilot=pilots[1]),
        },
        aircraft_member_index={"Viper 1-1": 0, "Viper 1-2": 1},
    )
    game = SimpleNamespace(logistics=logistics)
    return game, inv, unit_map, pilots


def test_mission_charges_the_base_rounding_racks_up() -> None:
    game, inv, unit_map, pilots = _setup()
    debriefing = SimpleNamespace(
        unit_map=unit_map,
        state_data=SimpleNamespace(
            weapons_fired={"Viper 1-1": {"AIM_120C": 2, "GBU_12": 1}}
        ),
        air_losses=SimpleNamespace(
            player=[
                SimpleNamespace(
                    flight=unit_map.aircraft["Viper 1-2"].flight, pilot=pilots[1]
                )
            ]
        ),
    )

    log = charge_weapon_use(game, debriefing)

    # 1-1 fired 2 AMRAAMs and half a rack; 1-2 was lost with everything.
    assert inv.items[AMRAAM["clsid"]].quantity == 10 - 2 - 2
    assert inv.items[RACK["clsid"]].quantity == 10 - 2  # 0.5 + 1, rounded up
    assert inv.items[TANK["clsid"]].quantity == 10 - 1
    assert log[0].startswith("Larnaca: used ")


def test_running_out_is_reported_and_never_negative() -> None:
    game, inv, unit_map, pilots = _setup(stock=1)
    debriefing = SimpleNamespace(
        unit_map=unit_map,
        state_data=SimpleNamespace(weapons_fired={"Viper 1-1": {"AIM_120C": 2}}),
        air_losses=SimpleNamespace(player=[]),
    )
    log = charge_weapon_use(game, debriefing)
    assert inv.items[AMRAAM["clsid"]].quantity == 0
    assert any("OUT OF" in line and "AIM-120C" in line for line in log)


def test_shortage_check_for_planning() -> None:
    game, inv, unit_map, _ = _setup(stock=3)
    base = unit_map.aircraft["Viper 1-1"].flight.departure
    short = weapon_shortages(game, base, F16, count=2)
    assert short == [f"{AMRAAM['name']} (3 of 4)"]
