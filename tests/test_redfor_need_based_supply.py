"""REDFOR resupply by need: bases below target, fed from the nearest spare units."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from game.ato.redfor_supply_planner import RedforSupplyPlanner, _select_units
from game.theater.player import Player
from game.theater.transitnetwork import TransitNetwork
from tests.test_redfor_planners import TANK, FakeCp, make_game, road

KM = 1000.0


def _settings(**overrides: Any) -> Any:
    values = dict(
        redfor_resupply_enabled=True,
        redfor_resupply_max_bases=3,
        redfor_resupply_max_distance_km=400,
        redfor_resupply_frontline_target=20,
        redfor_resupply_rear_target=6,
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
