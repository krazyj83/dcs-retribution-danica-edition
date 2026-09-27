"""REDFOR supply transport by distance.

Road convoy under 120 km (if road-connected), airlift preferring helicopters up
to 220 km and planes beyond. BLUEFOR supplies are player-flown and not tiered.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest
from dcs.vehicles import vehicle_map

from game.dcs.groundunittype import GroundUnitType
from game.logistics.transport_tiers import Tier, preferred_airlift, road_path, tier_for
from game.theater.player import Player
from game.theater.transitnetwork import TransitConnection, TransitNetwork

KM = 1000.0


# --- shared rules ------------------------------------------------------------------


@pytest.mark.parametrize(
    "km, tier",
    [
        (1, Tier.SHORT),
        (119.9, Tier.SHORT),
        (120, Tier.MEDIUM),
        (220, Tier.MEDIUM),
        (220.1, Tier.LONG),
        (600, Tier.LONG),
    ],
)
def test_distance_bands(km: float, tier: Tier) -> None:
    assert tier_for(km * KM) is tier


def test_airlift_preference_by_band() -> None:
    assert preferred_airlift(Tier.SHORT) == "helicopter"
    assert preferred_airlift(Tier.MEDIUM) == "helicopter"
    assert preferred_airlift(Tier.LONG) == "plane"


class Node:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


def test_road_path_uses_road_links_only() -> None:
    a, b, c, d = Node("A"), Node("B"), Node("C"), Node("D")
    network = TransitNetwork()
    network.link_with(a, b, TransitConnection.Road)  # type: ignore[arg-type]
    network.link_with(b, c, TransitConnection.Road)  # type: ignore[arg-type]
    network.link_with(a, d, TransitConnection.Airlift)  # type: ignore[arg-type]

    assert road_path(network, a, c) == [a, b, c]  # type: ignore[arg-type]
    assert road_path(network, a, d) is None  # type: ignore[arg-type]


TRUCK = next(GroundUnitType.for_dcs_type(vehicle_map["M 818"]))


# --- REDFOR ------------------------------------------------------------------------


class RedCp:
    def __init__(self, name: str, x_km: float, trucks: int = 8) -> None:
        self.id = name
        self.name = name
        self.captured = Player.RED
        self.can_deploy_ground_units = True
        self.base = SimpleNamespace(armor={TRUCK: trucks})
        self.position = SimpleNamespace(
            x=x_km * KM, distance_to_point=lambda o: abs(x_km * KM - o.x)
        )


class RecordingTransfers:
    def __init__(self) -> None:
        self.created: list[Any] = []

    def new_transfer(self, transfer: Any, now: Any) -> None:
        self.created.append(transfer)

    def __iter__(self) -> Any:
        return iter(self.created)


def _red_game(a: RedCp, b: RedCp, link: TransitConnection) -> Any:
    network = TransitNetwork()
    network.link_with(a, b, link)  # type: ignore[arg-type]
    return SimpleNamespace(
        settings=None,
        red=SimpleNamespace(transit_network=network, transfers=RecordingTransfers()),
        theater=SimpleNamespace(controlpoints=[a, b]),
        transit_network_for=lambda player: network,
    )


@pytest.mark.parametrize(
    "km, link, by_road, preferred",
    [
        (80, TransitConnection.Road, True, None),
        (80, TransitConnection.Airlift, False, "helicopter"),
        (180, TransitConnection.Road, False, "helicopter"),
        (300, TransitConnection.Airlift, False, "plane"),
    ],
)
def test_redfor_supply_uses_the_same_bands(
    km: float,
    link: TransitConnection,
    by_road: bool,
    preferred: Optional[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from game.ato import redfor_supply_planner as planner

    monkeypatch.setattr(planner, "airlift_possible", lambda game, a, b: True)
    game = _red_game(RedCp("A", 0), RedCp("B", km, trucks=0), link)

    planner.RedforSupplyPlanner(game).plan()

    created = game.red.transfers.created
    assert len(created) == 1
    assert created[0].request_airflift is (not by_road)
    assert created[0].preferred_airlift == preferred


def test_redfor_skips_an_airlift_no_red_aircraft_can_fly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from game.ato import redfor_supply_planner as planner

    monkeypatch.setattr(planner, "airlift_possible", lambda game, a, b: False)
    a, b = RedCp("A", 0), RedCp("B", 180, trucks=0)
    game = _red_game(a, b, TransitConnection.Airlift)

    planner.RedforSupplyPlanner(game).plan()

    assert game.red.transfers.created == []
    assert a.base.armor[TRUCK] == 8, "no units stripped for a flight that can't happen"


def test_redfor_does_not_stack_a_second_order_on_a_waiting_pair() -> None:
    from game.ato.redfor_supply_planner import RedforSupplyPlanner

    a, b = RedCp("A", 0), RedCp("B", 50, trucks=0)
    game = _red_game(a, b, TransitConnection.Road)

    RedforSupplyPlanner(game).plan()
    RedforSupplyPlanner(game).plan()  # next turn, first order still waiting

    assert [(t.origin.name, t.destination.name) for t in game.red.transfers] == [
        ("A", "B")
    ]


def _transport_squadron(home_km: float, helicopter: bool, owned: int = 4) -> Any:
    unit_type = SimpleNamespace(
        dcs_unit_type=SimpleNamespace(helicopter=helicopter),
        capable_of=lambda task: True,
    )
    return SimpleNamespace(
        owned_aircraft=owned,
        aircraft=unit_type,
        location=SimpleNamespace(position=_pos(home_km)),
    )


class _Base:
    def __init__(self, km: float, runway: bool = True) -> None:
        self.position = _pos(km)
        self.captured = Player.RED
        self.runway = runway

    def can_operate(self, aircraft: Any) -> bool:
        return self.runway or aircraft.dcs_unit_type.helicopter


def _pos(km: float) -> Any:
    return SimpleNamespace(x=km * KM, distance_to_point=lambda o: abs(km * KM - o.x))


@pytest.mark.parametrize(
    "squadron, origin_km, dest_km, dest_runway, possible",
    [
        # Helicopter: legs 50 / 150 / 200 km, all within 220 km.
        (lambda: _transport_squadron(0, helicopter=True), 50, 200, True, True),
        # Helicopter: drop-off -> home leg too long (250 km > 220 km).
        (lambda: _transport_squadron(0, helicopter=True), 50, 250, True, False),
        # Helicopter: home -> pickup leg too long (250 km > 220 km).
        (lambda: _transport_squadron(0, helicopter=True), 250, 300, True, False),
        # Helicopter: pickup -> drop-off leg too long; upstream never checked it.
        (lambda: _transport_squadron(0, helicopter=True), 10, 300, True, False),
        (lambda: _transport_squadron(0, helicopter=False), 10, 900, True, True),
        # Plane cannot land at a FARP.
        (lambda: _transport_squadron(0, helicopter=False), 10, 100, False, False),
        # A squadron with no aircraft does not count.
        (
            lambda: _transport_squadron(0, helicopter=False, owned=0),
            10,
            100,
            True,
            False,
        ),
    ],
)
def test_airlift_possible(
    squadron: Any, origin_km: float, dest_km: float, dest_runway: bool, possible: bool
) -> None:
    from game.ato.redfor_supply_planner import airlift_possible

    sq = squadron()
    game: Any = SimpleNamespace(
        air_wing_for=lambda player: SimpleNamespace(iter_squadrons=lambda: [sq])
    )
    origin, dest = _Base(origin_km), _Base(dest_km, runway=dest_runway)

    assert airlift_possible(game, origin, dest) is possible  # type: ignore[arg-type]


def test_airlift_puts_the_preferred_kind_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from game.transfers import AirliftPlanner

    near_plane = SimpleNamespace(
        aircraft=SimpleNamespace(dcs_unit_type=SimpleNamespace(helicopter=False)),
        untasked_aircraft=2,
        has_available_pilots=True,
    )
    far_helo = SimpleNamespace(
        aircraft=SimpleNamespace(dcs_unit_type=SimpleNamespace(helicopter=True)),
        untasked_aircraft=2,
        has_available_pilots=True,
    )
    near, far = SimpleNamespace(captured=Player.RED), SimpleNamespace(
        captured=Player.RED
    )
    squadrons = {id(near): [near_plane], id(far): [far_helo]}

    planner = AirliftPlanner.__new__(AirliftPlanner)
    planner.for_player = Player.RED
    planner.transfer = SimpleNamespace(  # type: ignore[assignment]
        position=None, preferred_airlift="helicopter", transport=None
    )
    planner.package = SimpleNamespace(flights=[])  # type: ignore[assignment]
    planner.game = SimpleNamespace(  # type: ignore[assignment]
        air_wing_for=lambda p: SimpleNamespace(
            auto_assignable_for_task_at=lambda task, cp: squadrons[id(cp)]
        )
    )
    monkeypatch.setattr(
        "game.transfers.ObjectiveDistanceCache.get_closest_airfields",
        lambda position: SimpleNamespace(closest_airfields=[near, far]),
    )
    monkeypatch.setattr(planner, "compatible_with_mission", lambda t, cp: True)
    used: list[Any] = []

    def fly(squadron: Any) -> int:
        used.append(squadron)
        planner.transfer.transport = object()  # type: ignore[assignment]
        return 1

    monkeypatch.setattr(planner, "create_airlift_flight", fly)

    planner.create_package_for_airlift(now=None)  # type: ignore[arg-type]

    assert used == [far_helo], "helicopter preferred over the nearer plane"
