"""Fuel trucks in convoys carry warehouse fuel between BLUEFOR bases."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from game.ato.redfor_supply_planner import _select_units
from game.dcs.groundunittype import GroundUnitType
from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.fuel import (
    deliver_truck_fuel,
    is_fuel_truck,
    lose_truck_fuel,
    truck_load,
)
from game.missiongenerator.playerconvoygenerator import (
    CONVOY_SIZE,
    PlayerConvoyGenerator,
)
from game.theater.player import Player
from game.transfers import TransferOrder

HEMTT = GroundUnitType.named("Fuel Truck M978 HEMTT")
ATZ10 = GroundUnitType.named("Fuel Truck ATZ-10")
TRUCK = GroundUnitType.named("Truck M818 6x6")
ABRAMS = GroundUnitType.named("M1A2 Abrams")
FUEL = WarehouseCategory.FUEL


def _game() -> Any:
    return SimpleNamespace(logistics=LogisticsManager())


def _base(game: Any, name: str, side: Player = Player.BLUE, fuel: float = 500) -> Any:
    cp = SimpleNamespace(
        id=uuid4(),
        name=name,
        captured=side,
        _coalition=SimpleNamespace(game=game),
        base=SimpleNamespace(armor={}, commission_units=lambda units: None),
    )
    if side.is_blue:
        wh = Warehouse(cp_id=cp.id, cp_name=name)
        wh.stock[FUEL].quantity = fuel
        game.logistics.add_warehouse(wh)
    return cp


def _fuel(game: Any, cp: Any) -> float:
    return game.logistics.get_warehouse(cp.id).stock[FUEL].quantity


def test_fuel_trucks_are_recognised() -> None:
    assert truck_load(HEMTT) == 38 and is_fuel_truck(ATZ10)
    assert not is_fuel_truck(TRUCK) and truck_load(ABRAMS) == 0


def test_arriving_truck_moves_its_load() -> None:
    game = _game()
    home, forward = _base(game, "Larnaca"), _base(game, "Paphos", fuel=100)

    line = deliver_truck_fuel(game, home, forward, HEMTT, 2)

    assert _fuel(game, home) == 500 - 76
    assert _fuel(game, forward) == 176
    assert line and "delivered 76 fuel to Paphos" in line
    assert game.logistics.pop_debrief_log() == [line]


def test_load_is_limited_by_the_origin_and_the_destination() -> None:
    game = _game()
    dry, full = _base(game, "Dry", fuel=10), _base(game, "Full", fuel=990)

    deliver_truck_fuel(game, dry, full, HEMTT)

    assert _fuel(game, full) == 1000  # took the 10 the origin had
    assert _fuel(game, dry) == 0

    game2 = _game()
    home, almost_full = _base(game2, "Home"), _base(game2, "Near", fuel=980)
    deliver_truck_fuel(game2, home, almost_full, HEMTT)
    assert _fuel(game2, almost_full) == 1000
    assert _fuel(game2, home) == 480  # only what fit left home


def test_destroyed_truck_loses_its_load() -> None:
    game = _game()
    home = _base(game, "Larnaca")

    lose_truck_fuel(game, home, ATZ10)

    assert _fuel(game, home) == 460


def test_redfor_trucks_carry_no_warehouse_fuel() -> None:
    game = _game()
    red_a, red_b = _base(game, "A", Player.RED), _base(game, "B", Player.RED)
    assert deliver_truck_fuel(game, red_a, red_b, ATZ10) is None
    assert lose_truck_fuel(game, red_a, ATZ10) is None


def test_transfer_convoy_delivers_and_loses_fuel() -> None:
    game = _game()
    home, forward = _base(game, "Larnaca"), _base(game, "Paphos", fuel=100)
    transfer = TransferOrder(home, forward, {HEMTT: 2, TRUCK: 3})

    transfer.kill_unit(HEMTT)  # one truck destroyed on the road
    transfer.disband_at(forward)  # the other arrives

    assert _fuel(game, home) == 500 - 38 - 38
    assert _fuel(game, forward) == 138


def test_surrounded_transfer_loses_its_trucks_fuel() -> None:
    game = _game()
    home, forward = _base(game, "Larnaca"), _base(game, "Paphos")
    transfer = TransferOrder(home, forward, {HEMTT: 2})

    transfer.kill_all()

    assert _fuel(game, home) == 500 - 76


def test_drawn_convoy_takes_up_to_two_spare_fuel_trucks() -> None:
    picked = PlayerConvoyGenerator._pick_units({TRUCK: 10, ABRAMS: 5, HEMTT: 3})

    assert picked[HEMTT] == 2
    assert sum(n for t, n in picked.items() if t is not HEMTT) == CONVOY_SIZE


def test_redfor_road_convoy_takes_fuel_trucks_only_by_road() -> None:
    cp: Any = SimpleNamespace(base=SimpleNamespace(armor={TRUCK: 6, ATZ10: 3}))

    by_road = _select_units(cp, 4, fuel_trucks=True)
    airlift = _select_units(cp, 4, fuel_trucks=False)

    assert by_road == {ATZ10: 2, TRUCK: 4}
    assert airlift == {TRUCK: 4}


def test_player_convoy_settlement_moves_fuel() -> None:
    from game.sim.missionresultsprocessor import MissionResultsProcessor

    game = _game()
    home, forward = _base(game, "Larnaca"), _base(game, "Paphos", fuel=100)
    home.base = SimpleNamespace(
        armor={HEMTT: 2},
        total_units_of_type=lambda t: 2,
        commission_units=lambda units: None,
    )
    forward.base = SimpleNamespace(commission_units=lambda units: None)
    units = {
        "t1": SimpleNamespace(
            name="t1", unit_type=HEMTT, origin=home, destination=forward
        ),
        "t2": SimpleNamespace(
            name="t2", unit_type=HEMTT, origin=home, destination=forward
        ),
    }
    debriefing: Any = SimpleNamespace(
        game=game,
        unit_map=SimpleNamespace(player_drawn_convoys=units),
        state_data=SimpleNamespace(player_convoy_arrivals=["t1"]),
        player_drawn_convoy_losses=[SimpleNamespace(name="t2")],
    )

    MissionResultsProcessor.commit_player_drawn_convoys(debriefing)

    assert _fuel(game, forward) == 138
    assert _fuel(game, home) == pytest.approx(500 - 38 - 38)
