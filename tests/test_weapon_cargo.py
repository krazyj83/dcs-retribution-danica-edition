"""Weapon transfers: cargo weight against what the aircraft can lift.

cargo = max take-off weight - empty weight - (fuel % x fuel capacity)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from dcs.helicopters import CH_47Fbl1, UH_1H
from dcs.weapons_data import Weapons

from game.logistics import LogisticsManager, TransferStatus, WeaponInventory
from game.logistics import transfer_flights
from game.theater.player import Player
from game.logistics.cargo import (
    cargo_aircraft,
    lb,
    manifest_summary,
    manifest_weight_kg,
    route_legs,
    weapon_weight_kg,
)
from tests.test_logistics_transfers import FakeAto, FakeCp, FakeFlight, FakePackage
from tests.test_logistics_transfers import _theater

HELLFIRE = str(Weapons.AGM_114K_Hellfire["clsid"])
GBU_12 = str(Weapons.GBU_12["clsid"])


def _aircraft(unit_type: Any) -> Any:
    return SimpleNamespace(dcs_unit_type=unit_type)


# --- weights ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fuel, cargo_lb",
    [(1.0, 18133), (0.5, 21500), (0.25, 23184)],  # Morten's CH-47F figures
)
def test_ch47f_cargo_matches_the_dcs_figures(fuel: float, cargo_lb: float) -> None:
    weights = cargo_aircraft(_aircraft(CH_47Fbl1))
    assert weights is not None
    assert lb(weights.max_kg) == pytest.approx(50001, abs=1)
    assert lb(weights.payload_kg(fuel)) == pytest.approx(cargo_lb, abs=2)


def test_aircraft_without_weight_data_is_not_checked() -> None:
    unknown = SimpleNamespace(id="SomeMod", fuel_max=1000)
    assert cargo_aircraft(_aircraft(unknown)) is None


def test_less_fuel_means_more_cargo() -> None:
    weights = cargo_aircraft(_aircraft(UH_1H))
    assert weights is not None
    assert weights.payload_kg(0.25) > weights.payload_kg(0.5) > weights.payload_kg(1)


def test_uh60l_and_dap_cargo_is_checked() -> None:
    from pydcs_extensions.uh60l.uh60l import UH_60L, UH_60L_DAP

    for unit_type in (UH_60L, UH_60L_DAP):
        weights = cargo_aircraft(_aircraft(unit_type))
        assert weights is not None
        # Mod data: 10659 kg max - 5675 kg empty - 1362 kg fuel.
        assert weights.payload_kg(1.0) == pytest.approx(3622.4, abs=1)


def test_weapon_weights_come_from_dcs() -> None:
    assert lb(weapon_weight_kg(HELLFIRE) or 0) == pytest.approx(99, abs=1)
    assert weapon_weight_kg("not-a-weapon") is None
    assert manifest_weight_kg({HELLFIRE: 20}) == pytest.approx(20 * 45.3)
    assert manifest_summary({HELLFIRE: 20}) == "20x AGM-114K Hellfire"


def test_route_legs() -> None:
    home, source, dest = FakeCp("H", 0), FakeCp("S", 50_000), FakeCp("D", 200_000)
    legs = route_legs(home, source, dest)  # type: ignore[arg-type]
    assert (legs.to_pickup, legs.pickup_to_drop, legs.drop_to_home) == (
        50_000,
        150_000,
        200_000,
    )
    assert legs.total == 400_000


# --- transfers ----------------------------------------------------------------------


class WeaponSetup:
    def __init__(self, hellfires: int = 50, dest_capacity: int = 250) -> None:
        self.source = FakeCp("Source", x=0)
        self.dest = FakeCp("Dest", x=50_000)
        self.lm = LogisticsManager()
        src = WeaponInventory(cp_id=self.source.id, cp_name="Source")  # type: ignore[arg-type]
        src.add_item(HELLFIRE, "AGM-114K", "Air-to-Ground Missile", hellfires)
        src.add_item(GBU_12, "GBU-12", "Bomb", 10)
        self.lm.set_weapon_inventory(src)
        self.dest_capacity = dest_capacity
        self.ato = FakeAto()
        self.game: Any = SimpleNamespace(
            turn=3,
            logistics=self.lm,
            theater=_theater(self.source, self.dest),
            blue=SimpleNamespace(ato=self.ato),
        )

    def stock(self, cp: FakeCp, clsid: str) -> int:
        inv = self.lm.get_weapon_inventory(cp.id)  # type: ignore[arg-type]
        if inv is None or clsid not in inv.items:
            return 0
        return inv.items[clsid].quantity

    def schedule(self, cargo: dict[str, int]) -> Any:
        return self.lm.schedule_weapon_transfer(
            self.source.id, self.dest.id, "", cargo, "CH-47F", 3, 0.5  # type: ignore[arg-type]
        )

    def fly(self, transfer: Any, lost: int = 0) -> list[str]:
        flight = FakeFlight(transfer.transfer_id, count=1)
        self.ato.packages.append(FakePackage(flight))
        self.lm.on_turn_end(self.game)
        debrief = SimpleNamespace(
            air_losses=SimpleNamespace(surviving_flight_members=lambda f: 1 - lost)
        )
        return self.lm.on_state_processed(self.game, debrief)  # type: ignore[arg-type]


def test_scheduling_takes_the_weapons_from_the_source() -> None:
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20, GBU_12: 4})
    assert t is not None and t.fuel_fraction == 0.5
    assert (s.stock(s.source, HELLFIRE), s.stock(s.source, GBU_12)) == (30, 6)


def test_not_enough_of_one_item_takes_nothing() -> None:
    s = WeaponSetup()
    assert s.schedule({HELLFIRE: 20, GBU_12: 11}) is None
    assert (s.stock(s.source, HELLFIRE), s.stock(s.source, GBU_12)) == (50, 10)


def test_delivery_adds_the_weapons_at_the_destination() -> None:
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20})
    log = s.fly(t)
    assert t.status is TransferStatus.DELIVERED and t.delivered == 20
    assert s.stock(s.dest, HELLFIRE) == 20
    assert "20x AGM-114K Hellfire delivered to Dest" in log[0]


def test_overflow_goes_back_to_the_source() -> None:
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20})
    dest = WeaponInventory(cp_id=s.dest.id, cp_name="Dest")  # type: ignore[arg-type]
    dest.add_item(HELLFIRE, "AGM-114K", "Air-to-Ground Missile", 245)
    s.lm.set_weapon_inventory(dest)
    s.fly(t)
    assert s.stock(s.dest, HELLFIRE) == 250
    assert s.stock(s.source, HELLFIRE) == 30 + 15


def test_shot_down_loses_the_weapons() -> None:
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20})
    s.fly(t, lost=1)
    assert t.status is TransferStatus.FAILED
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (30, 0)


def test_cancel_returns_the_weapons() -> None:
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20})
    assert s.lm.cancel_transfer(t.transfer_id)
    assert s.stock(s.source, HELLFIRE) == 50


def test_sync_keeps_weapon_stock_but_rereads_ground_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import game.logistics as logistics

    s = WeaponSetup()
    s.lm.get_weapon_inventory(s.source.id).items[HELLFIRE].quantity = 7  # type: ignore
    s.lm.get_weapon_inventory(s.source.id).add_item("M1A2", "Abrams", "Armour", 4)  # type: ignore

    def rebuilt(cp: Any, game: Any) -> WeaponInventory:
        inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)
        inv.add_item(HELLFIRE, "AGM-114K", "Air-to-Ground Missile", 5)
        inv.add_item("M1A2", "Abrams", "Armour", 2)
        return inv

    monkeypatch.setattr(logistics, "build_weapon_inventory", rebuilt)
    s.game.theater.player_points = lambda: [s.source]
    s.lm.sync_weapon_inventories(s.game)

    assert s.stock(s.source, HELLFIRE) == 7, "transferred stock not reset"
    assert s.stock(s.source, "M1A2") == 2, "garrison re-read"
    assert s.stock(s.source, GBU_12) == 10, "tracked weapon kept"


def test_old_category_transfers_still_label() -> None:
    from uuid import uuid4

    from game.logistics import LogisticsTransfer, WarehouseCategory

    t = LogisticsTransfer(
        "id", uuid4(), uuid4(), "", WarehouseCategory.FUEL, 200, "UH-1H", 1
    )
    assert t.cargo_label == "200 fuel"


# --- cargo placed in the mission ----------------------------------------------------


def test_sling_aircraft_get_one_crate_with_everything() -> None:
    from game.logistics.cargo import pack_crates

    crates = pack_crates({HELLFIRE: 20, GBU_12: 2}, internal=False)
    assert len(crates) == 1
    assert crates[0].mass_kg == pytest.approx(
        manifest_weight_kg({HELLFIRE: 20, GBU_12: 2})
    )


def test_internal_loaders_get_crates_of_at_most_1000_kg_per_weapon() -> None:
    from game.logistics.cargo import pack_crates

    crates = pack_crates({HELLFIRE: 50, GBU_12: 3}, internal=True)
    assert [c.contents for c in crates] == [
        {HELLFIRE: 22},
        {HELLFIRE: 22},
        {HELLFIRE: 6},
        {GBU_12: 3},
    ]
    assert all(c.mass_kg <= 1000 for c in crates)


def _mission_setup(home_is_source: bool, helicopter: bool = True) -> Any:
    from dcs import Mission
    from dcs.countries import USA
    from dcs.mapping import Point
    from dcs.terrain import Caucasus

    from game.ato.flighttype import FlightType
    from game.ato.starttype import StartType
    from game.missiongenerator.transfercargogenerator import TransferCargoGenerator

    mission = Mission(Caucasus())
    s = WeaponSetup()
    t = s.schedule({HELLFIRE: 20})
    source: Any = s.source
    source.is_fleet = False
    source.dcs_airport = None
    source.position = Point(0, 0, mission.terrain)
    home = source if home_is_source else FakeCp("Home")
    flight: Any = SimpleNamespace(
        flight_type=FlightType.LOGISTIC,
        transfer_id=t.transfer_id,
        unit_type=_aircraft(
            SimpleNamespace(
                id="UH-1H" if helicopter else "C-130J-30",
                helicopter=helicopter,
                fuel_max=631 if helicopter else 19692,
            )
        ),
        departure=home,
        start_type=StartType.COLD,
        client_count=1,
        squadron=SimpleNamespace(
            coalition=SimpleNamespace(
                faction=SimpleNamespace(country=SimpleNamespace(name=USA.name))
            )
        ),
    )
    s.game.blue.ato.packages = [SimpleNamespace(flights=[flight])]
    gen = TransferCargoGenerator(mission, s.game, SimpleNamespace(aircraft={}))  # type: ignore[arg-type]
    aircraft_at = Point(1000, 2000, mission.terrain)
    gen._lead_unit = lambda f: SimpleNamespace(position=aircraft_at, heading=0.0)  # type: ignore[method-assign, assignment]
    return mission, gen, t, aircraft_at


def _crates(mission: Any) -> list[Any]:
    return [
        g.units[0]
        for c in mission.coalition["blue"].countries.values()
        for g in c.static_group
    ]


def test_crate_is_placed_beside_the_helicopter_at_the_pickup_base() -> None:
    mission, gen, t, aircraft_at = _mission_setup(home_is_source=True)
    assert gen.generate() == 1
    (crate,) = _crates(mission)
    assert crate.can_cargo and crate.mass == round(20 * 45.3)
    assert crate.name.startswith(f"Cargo {t.transfer_id[:8]} 1/1: 20x AGM-114K")
    assert crate.position.distance_to_point(aircraft_at) == pytest.approx(25, abs=0.1)


def test_crates_wait_at_the_pickup_base_when_the_flight_starts_elsewhere() -> None:
    mission, gen, t, aircraft_at = _mission_setup(home_is_source=False)
    assert gen.generate() == 1
    (crate,) = _crates(mission)
    assert crate.position.distance_to_point(aircraft_at) > 1000  # at the source


def test_no_crates_on_a_ship() -> None:
    mission, gen, t, aircraft_at = _mission_setup(home_is_source=True)
    s_source = gen.game.theater.find_control_point_by_id(t.source_cp_id)
    s_source.is_fleet = True
    assert gen.generate() == 0 and _crates(mission) == []


# --- cargo planned on the flight (mission planner Cargo tab) ------------------------


def _flight_setup(target_owner: Player = Player.BLUE) -> Any:
    from game.logistics import DropZone, DropZoneType

    s = WeaponSetup()
    s.dest.captured = target_owner
    s.lm.add_drop_zone(
        DropZone(
            dz_id="dz1",
            name="North pad",
            cp_id=s.dest.id,  # type: ignore[arg-type]
            lat=0,
            lon=0,
            dz_type=list(DropZoneType)[0],
            coalition="blue",
        )
    )
    flight: Any = SimpleNamespace(
        transfer_id=None,
        departure=s.source,
        package=SimpleNamespace(target=s.dest),
        squadron=SimpleNamespace(player=Player.BLUE),
        unit_type=_aircraft(CH_47Fbl1),
        fuel=CH_47Fbl1.fuel_max / 2,
    )
    return s, flight


@pytest.fixture
def fake_cps_are_control_points(monkeypatch: pytest.MonkeyPatch) -> None:
    import game.theater

    monkeypatch.setattr(game.theater, "ControlPoint", FakeCp)


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_a_new_logistic_flight_gets_an_empty_transfer() -> None:
    from game.logistics.flight_cargo import attach_transfer

    s, flight = _flight_setup()
    t = attach_transfer(s.game, flight)
    assert flight.transfer_id == t.transfer_id
    assert (t.source_cp_id, t.dest_cp_id, t.dz_id) == ("Source", "Dest", "dz1")
    assert t.cargo == {} and t.fuel_fraction == pytest.approx(0.5)
    assert attach_transfer(s.game, flight) is t, "one transfer per flight"


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_logistic_flight_must_deliver_to_a_friendly_base() -> None:
    from game.ato.flightplans.planningerror import PlanningError
    from game.logistics.flight_cargo import attach_transfer

    s, flight = _flight_setup(target_owner=Player.RED)
    with pytest.raises(PlanningError):
        attach_transfer(s.game, flight)


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_loading_and_unloading_moves_stock() -> None:
    from game.logistics.flight_cargo import attach_transfer, release_flight_transfer

    s, flight = _flight_setup()
    t = attach_transfer(s.game, flight)
    assert s.lm.add_cargo(t, HELLFIRE, 20) == 20
    assert s.lm.add_cargo(t, GBU_12, 99) == 10, "only what is in stock"
    assert (s.stock(s.source, HELLFIRE), s.stock(s.source, GBU_12)) == (30, 0)
    assert s.lm.remove_cargo(t, HELLFIRE, 5) == 5
    assert t.cargo == {HELLFIRE: 15, GBU_12: 10} and t.quantity == 25

    release_flight_transfer(s.game, flight)  # flight deleted in the planner
    assert (s.stock(s.source, HELLFIRE), s.stock(s.source, GBU_12)) == (50, 10)


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_changing_the_pickup_returns_the_cargo() -> None:
    from game.logistics.flight_cargo import attach_transfer

    s, flight = _flight_setup()
    t = attach_transfer(s.game, flight)
    s.lm.add_cargo(t, HELLFIRE, 20)
    s.lm.change_pickup(t, "Other")
    assert t.cargo == {} and t.source_cp_id == "Other"
    assert s.stock(s.source, HELLFIRE) == 50


def test_an_empty_flight_transfer_is_not_flown_again() -> None:
    s = WeaponSetup()
    t = s.lm.create_flight_transfer(s.source.id, s.dest.id, "", "CH-47F", 3)  # type: ignore[arg-type]
    transfer_flights.plan_pending_transfer_flights(s.game, None)  # type: ignore[arg-type]
    assert t.status is TransferStatus.FAILED


def test_crate_positions_go_on_the_load_sheet() -> None:
    mission, gen, t, aircraft_at = _mission_setup(home_is_source=True)
    sheet: Any = SimpleNamespace(transfer_id=t.transfer_id, cargo_crates=[])
    other: Any = SimpleNamespace(transfer_id="someone else", cargo_crates=[])
    gen.mission_data = SimpleNamespace(flights=[sheet, other])
    gen.generate()
    ((label, mass, position, where),) = sheet.cargo_crates
    assert label == "20x AGM-114K Hellfire" and where.startswith("beside")
    assert other.cargo_crates == []


# --- settled from where the crates ended up (mission script reports) ----------------


class CrateSetup(WeaponSetup):
    """Source at x=0, destination at x=50 km, a third friendly base at x=100 km."""

    def __init__(self) -> None:
        from dcs.terrain import Caucasus

        super().__init__()
        self.third = FakeCp("Third", x=100_000)
        for cp in (self.source, self.dest, self.third):
            cp.is_fleet = False  # type: ignore[attr-defined]
            cp.dcs_airport = object()  # type: ignore[attr-defined]
        self.game.theater = _theater(self.source, self.dest, self.third)
        self.game.theater.terrain = Caucasus()
        self.t = self.schedule({HELLFIRE: 20})  # planned: taken from the source

    def crate(self, x: float, requested: bool = False, **extra: Any) -> dict[str, Any]:
        report = {
            "name": f"crate at {x}",
            "tid": self.t.transfer_id[:8],
            "source": "not-a-uuid",  # falls back to the transfer's source
            "contents": [{"clsid": HELLFIRE, "count": 10 if requested else 20}],
            "requested": requested,
            "destroyed": False,
            "exists": True,
            "x": x,
            "z": 0,
            "agl": 0.5,
        }
        report.update(extra)
        return report

    def settle(self, *crates: dict[str, Any], lost: int = 0) -> list[str]:
        flight = FakeFlight(self.t.transfer_id, count=1)
        self.ato.packages.append(FakePackage(flight))
        self.lm.on_turn_end(self.game)
        debrief = SimpleNamespace(
            air_losses=SimpleNamespace(surviving_flight_members=lambda f: 1 - lost),
            state_data=SimpleNamespace(cargo_crates=list(crates)),
        )
        return self.lm.on_state_processed(self.game, debrief)  # type: ignore[arg-type]


def test_planned_crate_set_down_at_the_destination_is_delivered() -> None:
    s = CrateSetup()
    log = s.settle(s.crate(50_300))
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (30, 20)
    assert s.t.status is TransferStatus.DELIVERED and s.t.delivered == 20
    assert "delivered to Dest" in log[0]


def test_planned_crate_never_picked_up_goes_back_to_stock() -> None:
    s = CrateSetup()
    log = s.settle(s.crate(25))
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (50, 0)
    assert s.t.status is TransferStatus.FAILED
    assert "back in stock" in log[0]


def test_crates_can_be_delivered_to_any_friendly_base() -> None:
    s = CrateSetup()
    s.settle(s.crate(99_000))
    assert s.stock(s.third, HELLFIRE) == 20


def test_ordered_crate_leaves_the_stock_only_when_delivered() -> None:
    s = CrateSetup()
    s.settle(
        s.crate(50_000, requested=True, name="R1"),
        s.crate(0, requested=True, name="R2"),
    )
    # R1 delivered (10 taken from the source), R2 never moved (no change);
    # the planned 20 were not reported, so they stay taken.
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (20, 10)


def test_destroyed_crates_are_lost() -> None:
    s = CrateSetup()
    s.settle(
        s.crate(10_000, destroyed=True, exists=False),
        s.crate(10_000, requested=True, destroyed=True, exists=False, name="R1"),
    )
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (20, 0)


def test_crate_still_on_the_hook_is_not_delivered() -> None:
    s = CrateSetup()
    s.settle(s.crate(50_000, agl=15.0))
    assert (s.stock(s.source, HELLFIRE), s.stock(s.dest, HELLFIRE)) == (50, 0)


@pytest.mark.parametrize("flight_lost, source_stock", [(False, 50), (True, 30)])
def test_crate_gone_without_trace(flight_lost: bool, source_stock: int) -> None:
    # e.g. still loaded inside the aircraft when the mission ended
    s = CrateSetup()
    s.settle(s.crate(0, exists=False), lost=1 if flight_lost else 0)
    assert s.stock(s.source, HELLFIRE) == source_stock


def test_without_crate_reports_the_flight_rule_still_applies() -> None:
    s = CrateSetup()
    s.settle()  # no cargo_crates in state.json (older mission)
    assert s.stock(s.dest, HELLFIRE) == 20


def test_mission_gets_the_cargo_menu_data() -> None:
    mission, gen, t, aircraft_at = _mission_setup(home_is_source=True)
    dest = gen.game.theater.find_control_point_by_id(t.dest_cp_id)
    from dcs.mapping import Point

    dest.is_fleet, dest.dcs_airport = False, None
    dest.position = Point(50_000, 0, mission.terrain)
    gen._group_of = lambda f: SimpleNamespace(name="Uzi 7", units=[])
    gen.generate()
    scripts = [
        str(action.dict().get("text", ""))
        for trigger in mission.triggerrules.triggers
        for action in trigger.actions
        if "dcsRetributionCargo" in str(action.dict().get("text", ""))
    ]
    assert len(scripts) == 1
    lua = scripts[0]
    assert '["Uzi 7"] = {["tid"] = "' + t.transfer_id[:8] in lua
    assert '["maxKg"] = 4310.0' in lua  # UH-1H
    assert '"AGM-114K"' in lua and '["qty"] = 30' in lua  # stock left after loading
    assert '"Cargo ' + t.transfer_id[:8] + " 1/1: 20x AGM-114K Hellfire" in lua
