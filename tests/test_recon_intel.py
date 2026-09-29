"""Enemy base supplies known from recon (game/logistics/intel.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from dcs.mapping import Point
from dcs.terrain import Caucasus

from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.intel import (
    STALE_AFTER_TURNS,
    intel_for,
    record_recon,
)
from game.logistics.supply_status import supply_status
from game.theater.player import Player

TERRAIN = Caucasus()


def _cp(name: str, x: float, side: Player = Player.RED) -> Any:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        captured=side,
        is_fleet=False,
        position=SimpleNamespace(
            x=x,
            y=0.0,
            latlng=lambda: SimpleNamespace(lat=44.0, lng=40.0),
        ),
    )


def _flight(name: str, xs: list[float], survivors: int) -> Any:
    return SimpleNamespace(
        name=name,
        survivors=survivors,
        flight_plan=SimpleNamespace(
            waypoints=[SimpleNamespace(position=Point(x, 0, TERRAIN)) for x in xs]
        ),
        __str__=lambda self: name,
    )


def _game(bases: list[Any], flights: list[Any]) -> Any:
    logistics = LogisticsManager()
    for cp in bases:
        wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
        wh.coalition = "red"
        logistics.add_warehouse(wh)
    return SimpleNamespace(
        logistics=logistics,
        settings=SimpleNamespace(redfor_logistics=True, logistics_unlimited_fuel=False),
        theater=SimpleNamespace(controlpoints=bases, ground_objects=[]),
        blue=SimpleNamespace(
            ato=SimpleNamespace(packages=[SimpleNamespace(flights=flights)])
        ),
        turn=5,
    )


def _debriefing(flights: list[Any]) -> Any:
    return SimpleNamespace(
        air_losses=SimpleNamespace(
            surviving_flight_members=lambda flight: flight.survivors
        )
    )


def test_surviving_flights_near_a_base_bring_back_its_stock() -> None:
    maykop, krymsk = _cp("Maykop", 0), _cp("Krymsk", 200_000)
    near, lost = _flight("Viper 1", [100_000, 20_000], 2), _flight(
        "Hawg 2", [200_000], 0
    )
    game = _game([maykop, krymsk], [near, lost])
    wh = game.logistics.get_warehouse(maykop.id)
    wh.stock[WarehouseCategory.FUEL].quantity = 300

    log = record_recon(game, _debriefing([near, lost]))

    assert log == ["Recon over Maykop: fuel Low (~30%), ammunition Good (~50%)"]
    report, age = intel_for(game, maykop)  # type: ignore[misc]
    assert report.fuel == 0.3 and age == 0
    assert intel_for(game, krymsk) is None  # its flight was shot down


def test_reports_go_stale_and_are_forgotten_on_capture() -> None:
    maykop = _cp("Maykop", 0)
    game = _game([maykop], [_flight("Viper 1", [0], 1)])
    record_recon(game, _debriefing([]))

    game.turn += STALE_AFTER_TURNS
    assert intel_for(game, maykop) is not None
    game.turn += 1
    assert intel_for(game, maykop) is None

    game.turn -= 1
    game.logistics.on_base_captured(maykop, Player.BLUE)
    maykop.captured = Player.RED
    assert intel_for(game, maykop) is None


def test_map_shows_enemy_bases_only_with_recon() -> None:
    maykop, krymsk = _cp("Maykop", 0), _cp("Krymsk", 200_000)
    game = _game([maykop, krymsk], [_flight("Viper 1", [0], 1)])
    game.logistics.get_warehouse(maykop.id).stock[
        WarehouseCategory.AMMUNITION
    ].quantity = 100
    record_recon(game, _debriefing([]))
    game.turn += 2

    (row,) = supply_status(game)

    assert row.cp is maykop and row.side == "red" and row.intel_age == 2
    assert row.ammunition == 10 and row.status == "critical"
