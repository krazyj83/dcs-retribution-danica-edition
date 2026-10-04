"""Cargo trucks and escort hold on player-drawn supply routes
(game/logistics/convoy_cargo.py, game/missiongenerator/playerconvoygenerator.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from dcs.mission import Mission

from game.ato.flighttype import FlightType
from game.logistics import LogisticsManager, WarehouseCategory, new_base_warehouse
from game.logistics.convoy_cargo import (
    AMMO_PER_TRUCK,
    CARGO_TRUCKS_PER_CONVOY,
    SUPPLIES_PER_TRUCK,
    cargo_truck_type,
    register,
    settle,
)
from game.missiongenerator.playerconvoygenerator import (
    CONVOY_SIZE,
    ESCORT_RADIUS_M,
    ESCORT_WAIT_S,
    PlayerConvoyGenerator,
)
from game.theater.convoyroute import ConvoyRouteTarget
from game.theater.player import Player
from game.unitmap import UnitMap
from tests.missiongenerator.test_playerconvoygenerator import (
    ABRAMS,
    BRADLEY,
    TERRAIN,
    _near_end,
    _near_start,
    _route,
    _unit,
)

CARGO = _unit("M 818")
TANKER = _unit("M978 HEMTT Tanker")
HUMVEE = _unit("UAZ-469")
AMMO, SUPPLIES = WarehouseCategory.AMMUNITION, WarehouseCategory.SUPPLIES


def _game(cps: list[Any], routes: list[Any], packages: list[Any] = ()) -> Any:  # type: ignore[assignment]
    faction = SimpleNamespace(
        name="Test faction",
        country=SimpleNamespace(name="USA"),
        liveries_overrides={},
        logistics_units={HUMVEE, TANKER, CARGO},
    )
    coalition = SimpleNamespace(
        faction=faction, ato=SimpleNamespace(packages=list(packages))
    )
    for cp in cps:
        cp.id = uuid.uuid4()
    by_id = {cp.id: cp for cp in cps}
    return SimpleNamespace(
        theater=SimpleNamespace(
            terrain=TERRAIN,
            controlpoints=cps,
            find_control_point_by_id=lambda i: by_id[i],
        ),
        coalition_for=lambda player: coalition,
        player_convoy_routes={r.id: r for r in routes},
        logistics=LogisticsManager(),
    )


def _escort_package(
    route: Any, flight_type: FlightType = FlightType.CONVOY_ESCORT
) -> Any:
    target = ConvoyRouteTarget(
        name=route.name, position=TERRAIN.map_view_default.position, route_id=route.id
    )
    flight = SimpleNamespace(flight_type=flight_type)
    return SimpleNamespace(target=target, flights=[flight]), flight


def _holds(group: Any) -> list[Any]:
    return [t for t in group.points[0].tasks if t.dict()["id"] == "ControlledTask"]


# --- the trucks -------------------------------------------------------------------


def test_the_cargo_truck_is_the_factions_truck_not_a_jeep_or_tanker() -> None:
    faction = SimpleNamespace(logistics_units={HUMVEE, TANKER, CARGO})
    assert cargo_truck_type(faction) is CARGO  # type: ignore[arg-type]
    assert cargo_truck_type(SimpleNamespace(logistics_units={HUMVEE})) is None  # type: ignore[arg-type]


def test_cargo_trucks_follow_the_borrowed_vehicles() -> None:
    source = _near_start("Source", {BRADLEY: 3, ABRAMS: 1})
    delivery = _near_end("Delivery", {})
    route = _route()
    game = _game([source, delivery], [route])
    mission, unit_map = Mission(TERRAIN), UnitMap()
    PlayerConvoyGenerator(mission, game, unit_map).generate()

    (group,) = mission.country("USA").vehicle_group
    assert len(group.units) == 4 + CARGO_TRUCKS_PER_CONVOY
    trucks = group.units[4:]
    assert {u.type for u in trucks} == {CARGO.dcs_unit_type.id}
    # Only the borrowed vehicles are the base's; the trucks carry its stock.
    assert len(unit_map.player_drawn_convoys) == 4
    assert set(game.logistics._convoy_cargo_trucks) == {str(u.name) for u in trucks}
    assert not _holds(group), "no escort flight: drives off at once"


def test_a_base_with_no_spare_vehicles_still_sends_trucks() -> None:
    source = _near_start("Source", {})
    delivery = _near_end("Delivery", {})
    game = _game([source, delivery], [_route()])
    mission, unit_map = Mission(TERRAIN), UnitMap()
    PlayerConvoyGenerator(mission, game, unit_map).generate()
    (group,) = mission.country("USA").vehicle_group
    assert len(group.units) == CARGO_TRUCKS_PER_CONVOY
    assert unit_map.player_drawn_convoys == {}
    entry = next(iter(game.logistics._convoy_cargo_trucks.values()))
    assert (entry["origin"], entry["destination"]) == (source.id, delivery.id)  # type: ignore[attr-defined]


# --- escort hold --------------------------------------------------------------------


def test_a_route_with_an_escort_flight_waits_for_it() -> None:
    source = _near_start("Source", {BRADLEY: 2})
    delivery = _near_end("Delivery", {})
    route = _route()
    package, escort = _escort_package(route)
    other_package, _ = _escort_package(_route("Other road"))
    game = _game([source, delivery], [route], [package, other_package])
    mission, unit_map = Mission(TERRAIN), UnitMap()
    generator = PlayerConvoyGenerator(mission, game, unit_map)
    generator.generate()

    (group,) = mission.country("USA").vehicle_group
    (hold,) = _holds(group)
    task = hold.dict()
    assert task["id"] == "ControlledTask"
    assert task["params"]["task"]["id"] == "Hold"
    stop = task["params"]["stopCondition"]
    assert stop["userFlag"] == "convoy-go-1" and stop["userFlagValue"] is True
    assert stop["duration"] == ESCORT_WAIT_S

    unit_map.aircraft["Escort 1-1"] = SimpleNamespace(flight=escort)  # type: ignore[assignment]
    unit_map.aircraft["Someone else"] = SimpleNamespace(flight=object())  # type: ignore[assignment]
    data = generator.script_data(unit_map)
    (convoy,) = data["convoys"]
    assert convoy["flag"] == "convoy-go-1" and convoy["escorts"] == ["Escort 1-1"]
    assert (convoy["startX"], convoy["startZ"]) == (
        group.points[0].position.x,
        group.points[0].position.y,
    )
    assert data["escortRadius"] == ESCORT_RADIUS_M == 9260
    assert data["escortWait"] == 3600


def test_a_barcap_over_the_route_does_not_hold_the_convoy() -> None:
    source = _near_start("Source", {BRADLEY: 2})
    route = _route()
    package, _ = _escort_package(route, FlightType.BARCAP)
    game = _game([source, _near_end("Delivery", {})], [route], [package])
    mission = Mission(TERRAIN)
    PlayerConvoyGenerator(mission, game, UnitMap()).generate()
    (group,) = mission.country("USA").vehicle_group
    assert not _holds(group)


# --- settling the loads -----------------------------------------------------------


class Base:
    def __init__(self, name: str, owner: Player = Player.BLUE) -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.captured = owner


def _world(source_ammo: float = 500) -> Any:
    source, dest = Base("Source"), Base("Delivery")
    lm = LogisticsManager()
    for cp in (source, dest):
        lm.add_warehouse(new_base_warehouse(cp))
    lm.get_warehouse(source.id).stock[AMMO].quantity = source_ammo  # type: ignore[union-attr]
    lm.get_warehouse(source.id).stock[SUPPLIES].quantity = 500  # type: ignore[union-attr]
    lm.get_warehouse(dest.id).stock[AMMO].quantity = 0  # type: ignore[union-attr]
    lm.get_warehouse(dest.id).stock[SUPPLIES].quantity = 0  # type: ignore[union-attr]
    by_id = {source.id: source, dest.id: dest}
    game = SimpleNamespace(
        logistics=lm,
        theater=SimpleNamespace(find_control_point_by_id=lambda i: by_id[i]),
    )
    register(game, ["T1", "T2", "T3", "T4"], source, dest)  # type: ignore[arg-type]
    return game, source, dest


def _qty(game: Any, base: Base, category: WarehouseCategory) -> float:
    return float(game.logistics.get_warehouse(base.id).stock[category].quantity)


def test_arrived_trucks_deliver_and_destroyed_ones_lose_their_load() -> None:
    game, source, dest = _world()
    lines = settle(game, killed=["T3"], arrived=["T1", "T2"])  # T4 still on the road
    assert _qty(game, dest, AMMO) == 2 * AMMO_PER_TRUCK
    assert _qty(game, dest, SUPPLIES) == 2 * SUPPLIES_PER_TRUCK
    assert _qty(game, source, AMMO) == 500 - 3 * AMMO_PER_TRUCK
    assert lines[0] == (
        "2 cargo truck(s) from Source delivered 50 ammunition and 50 supplies "
        "to Delivery"
    )
    assert "1 cargo truck(s) from Source destroyed" in lines[1]
    assert game.logistics._convoy_cargo_trucks == {}, "settled once"
    assert settle(game, killed=["T3"], arrived=["T1"]) == []


def test_trucks_carry_only_what_the_source_has() -> None:
    game, source, dest = _world(source_ammo=30)
    settle(game, killed=[], arrived=["T1", "T2", "T3", "T4"])
    assert _qty(game, dest, AMMO) == 30 and _qty(game, source, AMMO) == 0


def test_a_lost_source_moves_nothing() -> None:
    game, source, dest = _world()
    source.captured = Player.RED
    assert settle(game, killed=["T1"], arrived=["T2"]) == []
    assert _qty(game, dest, AMMO) == 0


def test_old_saves_have_no_trucks() -> None:
    state = dict(LogisticsManager().__dict__)
    state.pop("_convoy_cargo_trucks", None)
    restored = LogisticsManager.__new__(LogisticsManager)
    restored.__setstate__(state)
    game = SimpleNamespace(logistics=restored)
    assert settle(game, killed=[], arrived=[]) == []  # type: ignore[arg-type]
    assert CONVOY_SIZE == 4
