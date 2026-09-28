"""REDFOR warehouse fuel and ammunition (game/logistics/redfor.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from dcs.planes import F_16C_50, Su_27

from game.ato.flighttype import FlightType
from game.dcs.groundunittype import GroundUnitType
from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.capture import on_base_captured
from game.logistics.fuel import deliver_truck_fuel, lose_truck_fuel
from game.logistics.redfor import (
    AMMO_PER_A2G_AIRCRAFT,
    apply_supply_limits,
    depot_factor,
    intel_estimate,
    resupply,
    use_red_sortie_stock,
)
from game.theater.player import Player

FUEL, AMMO = WarehouseCategory.FUEL, WarehouseCategory.AMMUNITION
SU27_FUEL = Su_27.fuel_max / 200


class _Ato:
    def __init__(self, packages: list[Any]) -> None:
        self.packages = packages

    def remove_package(self, package: Any) -> None:
        self.packages.remove(package)


def _cp(name: str, side: Player = Player.RED) -> Any:
    return SimpleNamespace(id=uuid4(), name=name, captured=side)


def _flight(base: Any, count: int, task: FlightType, dcs_type: Any = Su_27) -> Any:
    return SimpleNamespace(
        departure=base,
        count=count,
        flight_type=task,
        unit_type=SimpleNamespace(dcs_unit_type=dcs_type),
    )


def _package(*flights: Any) -> Any:
    return SimpleNamespace(flights=list(flights))


def _game(*bases: Any, packages: list[Any] | None = None, **settings: Any) -> Any:
    logistics = LogisticsManager()
    for b in bases:
        wh = Warehouse(cp_id=b.id, cp_name=b.name)
        wh.coalition = "blue" if b.captured.is_blue else "red"
        logistics.add_warehouse(wh)
    options = dict(redfor_logistics=True, logistics_unlimited_fuel=False)
    options.update(settings)
    messages: list[tuple[str, str]] = []
    return SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(**options),
        theater=SimpleNamespace(controlpoints=list(bases), ground_objects=[]),
        red=SimpleNamespace(ato=_Ato(packages or [])),
        turn=3,
        messages=messages,
        message=lambda title, text="": messages.append((title, text)),
    )


def _stock(game: Any, cp: Any, cat: WarehouseCategory) -> float:
    return game.logistics.get_warehouse(cp.id).stock[cat].quantity


def test_red_sorties_use_fuel_and_ammunition() -> None:
    maykop = _cp("Maykop")
    game = _game(
        maykop,
        packages=[
            _package(_flight(maykop, 4, FlightType.BARCAP)),
            _package(_flight(maykop, 2, FlightType.STRIKE)),
        ],
    )

    use_red_sortie_stock(game)

    assert _stock(game, maykop, FUEL) == pytest.approx(500 - 6 * SU27_FUEL)
    assert _stock(game, maykop, AMMO) == 500 - 4 * 1 - 2 * AMMO_PER_A2G_AIRCRAFT


def test_nothing_happens_with_the_setting_off() -> None:
    maykop = _cp("Maykop")
    game = _game(
        maykop,
        packages=[_package(_flight(maykop, 4, FlightType.BARCAP))],
        redfor_logistics=False,
    )
    use_red_sortie_stock(game)
    assert apply_supply_limits(game, game.red.ato) == []
    assert resupply(game) == []
    assert _stock(game, maykop, FUEL) == 500


def test_packages_beyond_the_fuel_are_grounded_last_planned_first() -> None:
    maykop = _cp("Maykop")
    game = _game(maykop)
    game.logistics.get_warehouse(maykop.id).stock[FUEL].quantity = 100
    capa = _package(_flight(maykop, 4, FlightType.BARCAP))  # ~117 fuel
    strike = _package(_flight(maykop, 2, FlightType.STRIKE))
    ferry = _package(_flight(maykop, 2, FlightType.FERRY))
    game.red.ato.packages = [capa, strike, ferry]

    log = apply_supply_limits(game, game.red.ato)

    # The ferry is never grounded; the strike (planned after the CAP) goes
    # first, then the CAP still doesn't fit.
    assert game.red.ato.packages == [ferry]
    assert log == ["REDFOR Maykop: 2 package(s) grounded, not enough fuel"]
    assert game.messages[0][0] == "Intel: REDFOR short of fuel at Maykop"
    rows = intel_estimate(game, maykop)
    assert rows[-1][1] == "2 package(s) grounded (short of fuel)"


def test_no_ammunition_grounds_only_combat_flights() -> None:
    maykop = _cp("Maykop")
    game = _game(maykop)
    game.logistics.get_warehouse(maykop.id).stock[AMMO].quantity = 5
    cap = _package(_flight(maykop, 2, FlightType.BARCAP))  # 2 ammo
    strike = _package(_flight(maykop, 2, FlightType.STRIKE))  # 8 ammo
    awacs = _package(_flight(maykop, 1, FlightType.AEWC))
    game.red.ato.packages = [cap, strike, awacs]

    apply_supply_limits(game, game.red.ato)

    assert game.red.ato.packages == [cap, awacs]


def test_blue_packages_are_never_touched() -> None:
    blue = _cp("Batumi", Player.BLUE)
    game = _game(blue)
    game.logistics.get_warehouse(blue.id).stock[FUEL].quantity = 0
    ato = _Ato([_package(_flight(blue, 4, FlightType.BARCAP, F_16C_50))])
    apply_supply_limits(game, ato)
    assert len(ato.packages) == 1


def _depot(cp: Any, category: str, alive: list[bool]) -> Any:
    return SimpleNamespace(
        category=category,
        control_point=cp,
        units=[SimpleNamespace(alive=a) for a in alive],
    )


def test_resupply_scales_with_the_depots_left_once_per_turn() -> None:
    maykop = _cp("Maykop")
    game = _game(maykop, redfor_fuel_per_turn=60)
    game.theater.ground_objects = [
        _depot(maykop, "fuel", [True, False]),
        _depot(maykop, "ammo", [True, True]),
    ]
    assert depot_factor(game, "fuel") == 0.5

    resupply(game)
    resupply(game)  # same turn: nothing more

    assert _stock(game, maykop, FUEL) == 530
    assert _stock(game, maykop, AMMO) == 540


def test_red_fuel_trucks_carry_and_lose_fuel_with_the_setting_on() -> None:
    a, b = _cp("A"), _cp("B")
    game = _game(a, b)
    hemtt = GroundUnitType.named("Fuel Truck ATZ-10")

    deliver_truck_fuel(game, a, b, hemtt)
    lose_truck_fuel(game, a, hemtt)

    assert _stock(game, b, FUEL) == 540
    assert _stock(game, a, FUEL) == 420
    assert game.logistics.pop_debrief_log() == []  # not in the player's debrief


def test_capture_updates_the_warehouse_side() -> None:
    base = _cp("Kobuleti", Player.BLUE)
    logistics = LogisticsManager()
    logistics.add_warehouse(Warehouse(cp_id=base.id, cp_name=base.name))

    on_base_captured(logistics, base, Player.RED)

    assert logistics.warehouses_for_coalition("blue") == []
    assert len(logistics.warehouses_for_coalition("red")) == 1


def test_intel_estimate_rounds_like_intel() -> None:
    maykop = _cp("Maykop")
    game = _game(maykop)
    game.logistics.get_warehouse(maykop.id).stock[FUEL].quantity = 130
    rows = {label: text for label, text, _ in intel_estimate(game, maykop)}
    assert rows == {"Fuel": "Critical (~10%)", "Ammunition": "Good (~50%)"}


def test_resupply_gives_back_what_was_used_scaled_by_depots() -> None:
    maykop = _cp("Maykop")
    game = _game(
        maykop,
        packages=[_package(_flight(maykop, 4, FlightType.STRIKE))],
        redfor_fuel_per_turn=0,
    )
    use_red_sortie_stock(game)
    used = 4 * SU27_FUEL
    assert _stock(game, maykop, FUEL) == pytest.approx(500 - used)

    resupply(game)  # every depot standing: back where it was
    assert _stock(game, maykop, FUEL) == pytest.approx(500)
    assert _stock(game, maykop, AMMO) == pytest.approx(500)

    game.turn += 1
    use_red_sortie_stock(game)
    game.theater.ground_objects = [_depot(maykop, "fuel", [True, False])]
    resupply(game)  # half the fuel depot gone: half the fuel back
    assert _stock(game, maykop, FUEL) == pytest.approx(500 - used / 2)


def test_new_red_warehouses_start_full() -> None:
    from game.logistics.redfor import ensure_red_warehouses

    maykop = _cp("Maykop")
    game = _game()
    game.theater.controlpoints = [maykop]
    ensure_red_warehouses(game)
    wh = game.logistics.get_warehouse(maykop.id)
    assert wh.coalition == "red"
    assert wh.stock[FUEL].quantity == wh.stock[AMMO].quantity == 2000
    assert wh.stock[FUEL].capacity == 2000
