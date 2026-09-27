"""REDFOR resupply by need: bases below target, fed from the nearest spare units."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from game.ato.redfor_supply_planner import RedforSupplyPlanner, _select_units
from game.theater.player import Player
from game.theater.transitnetwork import TransitNetwork
from tests.test_redfor_planners import (
    SHILKA,
    STRELA,
    T72,
    TANK,
    FakeCp,
    make_game,
    road,
)

KM = 1000.0


def _settings(**overrides: Any) -> Any:
    values = dict(
        redfor_resupply_enabled=True,
        redfor_resupply_max_bases=3,
        redfor_resupply_max_distance_km=400,
        redfor_resupply_frontline_target=20,
        redfor_resupply_rear_target=6,
        redfor_main_base_enabled=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _plan(
    cps: list[FakeCp], links: list[tuple[FakeCp, FakeCp]], **settings: Any
) -> Any:
    network = TransitNetwork()
    for a, b in links:
        road(network, a, b)
    game = make_game(cps, network)
    game.settings = _settings(**settings)
    RedforSupplyPlanner(game).plan()
    return game.red.transfers.created


def _cp(name: str, km: float, armor: int, frontline: bool = False) -> FakeCp:
    return FakeCp(
        name, Player.RED, x=km * KM, armor=armor, has_active_frontline=frontline
    )


def test_full_nearest_base_is_skipped_for_the_next_one() -> None:
    source = _cp("Source", 0, armor=20)
    full = _cp("Full", 10, armor=6)  # at its rear target
    short = _cp("Short", 30, armor=0)

    created = _plan([source, full, short], [(source, full), (full, short)])

    # One order per pair while it is waiting; the rest follows next turn.
    assert [(t.origin.name, t.destination.name, t.size) for t in created] == [
        ("Source", "Short", 4)
    ]


def test_frontline_base_is_served_first() -> None:
    source = _cp("Source", 0, armor=40)
    rear = _cp("Rear", 5, armor=0)
    front = _cp("Front", 50, armor=0, frontline=True)

    created = _plan(
        [source, rear, front],
        [(source, rear), (source, front)],
        redfor_resupply_max_bases=1,
    )

    assert [t.destination.name for t in created] == ["Front"]


def test_nearest_base_with_spare_units_supplies() -> None:
    needy = _cp("Needy", 0, armor=2)
    far = _cp("Far", 60, armor=20)
    near = _cp("Near", 20, armor=20)

    created = _plan([needy, far, near], [(needy, far), (needy, near)])

    assert created[0].origin is near


def test_supplier_keeps_its_own_target() -> None:
    source = _cp("Source", 0, armor=8)  # rear target 6: 2 spare
    short = _cp("Short", 10, armor=0)

    created = _plan([source, short], [(source, short)])

    assert sum(t.size for t in created) == 2


def test_units_already_on_their_way_count() -> None:
    source = _cp("Source", 0, armor=20)
    short = _cp("Short", 10, armor=2)
    other = _cp("Other", 20, armor=20)
    network = TransitNetwork()
    road(network, source, short)
    road(network, short, other)
    game = make_game([source, short, other], network)
    game.settings = _settings()
    # 4 units already heading to Short from Other: it will be at its target.
    game.red.transfers.created.append(
        SimpleNamespace(origin=other, destination=short, units={TANK: 4})
    )

    RedforSupplyPlanner(game).plan()

    assert len(game.red.transfers.created) == 1


def test_full_bases_get_nothing() -> None:
    a = _cp("A", 0, armor=10)
    b = _cp("B", 10, armor=10)

    assert _plan([a, b], [(a, b)]) == []


def test_select_units_takes_a_mix_from_the_most_plentiful() -> None:
    cp: Any = SimpleNamespace(base=SimpleNamespace(armor={"T-72": 6, "BMP": 2}))

    assert _select_units(cp, 4) == {"T-72": 4}
    assert _select_units(cp, 8) == {"T-72": 6, "BMP": 2}


# --- main supply base ---------------------------------------------------------------


def _hub_game(cps: list[FakeCp], links: list[tuple[FakeCp, FakeCp]], **kw: Any) -> Any:
    network = TransitNetwork()
    for a, b in links:
        road(network, a, b)
    game = make_game(cps, network)
    game.settings = _settings(redfor_main_base_enabled=True, **kw)
    return game


def test_main_base_is_a_rear_factory_base_furthest_from_the_front() -> None:
    front = _cp("Front", 0, armor=20, frontline=True)
    near = _cp("Near", 20, armor=6)
    far = _cp("Far", 90, armor=6)
    factory = _cp("Factory", 60, armor=6)
    factory.has_factory = True  # type: ignore[attr-defined]
    game = _hub_game([front, near, far, factory], [])
    planner = RedforSupplyPlanner(game)

    hub = planner.main_base(planner._bases())

    assert hub is not None and hub.cp is factory
    factory.has_factory = False  # type: ignore[attr-defined]
    hub = planner.main_base(planner._bases())
    assert hub is not None and hub.cp is far


def test_frontline_base_is_fed_from_the_main_base_first() -> None:
    front = _cp("Front", 0, armor=0, frontline=True)
    close = _cp("Close", 20, armor=30)
    hub = _cp("Hub", 60, armor=30)
    hub.has_factory = True  # type: ignore[attr-defined]
    game = _hub_game(
        [front, close, hub],
        [(front, close), (close, hub)],
        redfor_resupply_max_bases=1,
    )

    RedforSupplyPlanner(game).plan()

    assert [(t.origin.name, t.destination.name) for t in game.red.transfers] == [
        ("Hub", "Front")
    ]


def test_rear_bases_send_spare_units_to_the_main_base() -> None:
    front = _cp("Front", 0, armor=20, frontline=True)  # at target
    hub = _cp("Hub", 60, armor=6)
    hub.has_factory = True  # type: ignore[attr-defined]
    rear = _cp("Rear", 80, armor=9)  # 3 spare
    game = _hub_game([front, hub, rear], [(front, hub), (hub, rear)])

    RedforSupplyPlanner(game).plan()

    assert [
        (t.origin.name, t.destination.name, t.size) for t in game.red.transfers
    ] == [("Rear", "Hub", 3)]


def test_frontline_spare_units_stay_at_the_front() -> None:
    front = _cp("Front", 0, armor=30, frontline=True)
    hub = _cp("Hub", 60, armor=6)
    game = _hub_game([front, hub], [(front, hub)])

    RedforSupplyPlanner(game).plan()

    assert game.red.transfers.created == []


# --- convoy escorts ----------------------------------------------------------------


def _history(bai: int) -> Any:
    from game.ato.flighttype import FlightType

    return SimpleNamespace(count=lambda ft: bai if ft is FlightType.BAI else 0)


def _escort_game(bai: int, armor: dict[Any, int], km: float = 30) -> Any:
    source = _cp("Source", 0, armor=0)
    source.base.armor = dict(armor)
    short = _cp("Short", km, armor=0)
    game = _hub_game([source, short], [(source, short)])
    game.settings.redfor_main_base_enabled = False
    game.bluefor_mission_history = _history(bai)
    return game


def test_convoy_takes_a_shorad_escort_after_heavy_bai() -> None:
    game = _escort_game(bai=3, armor={T72: 12, SHILKA: 2})

    RedforSupplyPlanner(game).plan()

    (convoy,) = game.red.transfers.created
    assert convoy.units == {SHILKA: 1, T72: 3}


def test_no_escort_without_bai() -> None:
    game = _escort_game(bai=0, armor={T72: 12, SHILKA: 2})

    RedforSupplyPlanner(game).plan()

    (convoy,) = game.red.transfers.created
    assert convoy.units == {T72: 4}


def test_no_escort_when_the_base_has_no_air_defence() -> None:
    game = _escort_game(bai=3, armor={T72: 12})

    RedforSupplyPlanner(game).plan()

    (convoy,) = game.red.transfers.created
    assert convoy.units == {T72: 4}


def test_airlift_takes_no_escort(monkeypatch: Any) -> None:
    from game.ato import redfor_supply_planner as planner

    monkeypatch.setattr(planner, "airlift_possible", lambda game, a, b: True)
    game = _escort_game(bai=3, armor={T72: 12, STRELA: 2}, km=180)

    RedforSupplyPlanner(game).plan()

    (airlift,) = game.red.transfers.created
    assert airlift.request_airflift
    assert STRELA not in airlift.units


def test_heavy_bai_buys_shorad_for_convoy_bases_without_one() -> None:
    from game.ato.redfor_adaptive_planner import RedforAdaptivePlanner

    big = _cp("Big", 0, armor=30)
    medium = _cp("Medium", 10, armor=20)
    covered = _cp("Covered", 20, armor=25)
    covered_armor: dict[Any, int] = covered.base.armor
    covered_armor[SHILKA] = 1
    small = _cp("Small", 30, armor=4)  # sends nothing
    game = make_game(
        [big, medium, covered, small],
        frontline_units=(SHILKA, STRELA, T72),
        budget=100,
    )

    RedforAdaptivePlanner(game)._counter_bai(count=4)  # heavy: 2 bases

    assert big.ground_unit_orders.units == {STRELA: 1}
    assert medium.ground_unit_orders.units == {STRELA: 1}
    assert covered.ground_unit_orders.units == {}
    assert small.ground_unit_orders.units == {}
    assert game.red.budget == 100 - 2 * STRELA.price


def test_moderate_bai_buys_one_escort() -> None:
    from game.ato.redfor_adaptive_planner import RedforAdaptivePlanner

    big = _cp("Big", 0, armor=30)
    medium = _cp("Medium", 10, armor=20)
    game = make_game([big, medium], frontline_units=(SHILKA, STRELA), budget=100)

    RedforAdaptivePlanner(game)._counter_bai(count=2)

    assert big.ground_unit_orders.units == {STRELA: 1}
    assert medium.ground_unit_orders.units == {}
