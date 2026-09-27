"""REDFOR supply/adaptive planners.

``ControlPoint.captured`` is a ``Player`` enum. Every member is truthy, so the
old ``not cp.captured`` / ``cp.captured or ...`` checks matched no red base and
both planners silently did nothing. These tests pin the ``.is_red`` checks, the
route guard that stops ``new_transfer()`` deleting units it cannot route, the
SEAD counter (which used to import a class that does not exist) and the
queueing of aircraft requests across the turn boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from game.ato.flighttype import FlightType
from game.ato.redfor_adaptive_planner import RedforAdaptivePlanner
from game.ato.redfor_supply_planner import RedforSupplyPlanner, has_transfer_route
from game.coalition import Coalition
from game.data.units import UnitClass
from game.procurement import AircraftProcurementRequest
from game.theater.player import Player
from game.theater.transitnetwork import TransitConnection, TransitNetwork

TANK = "T-72B"


@dataclass(frozen=True)
class FakeUnit:
    name: str
    unit_class: UnitClass
    price: int

    def __str__(self) -> str:
        return self.name


SHILKA = FakeUnit("ZSU-23-4", UnitClass.AAA, 6)
STRELA = FakeUnit("SA-13", UnitClass.SHORAD, 12)
TUNGUSKA = FakeUnit("SA-19", UnitClass.SHORAD, 20)
T72 = FakeUnit("T-72B", UnitClass.TANK, 10)


class RecordingOrders:
    def __init__(self) -> None:
        self.units: dict[Any, int] = {}

    def order(self, units: dict[Any, int]) -> None:
        for unit, count in units.items():
            self.units[unit] = self.units.get(unit, 0) + count


@dataclass(eq=False)
class FakeSquadron:
    tasks: set[FlightType]

    def can_auto_assign(self, task: FlightType) -> bool:
        return task in self.tasks


@dataclass(eq=False)
class FakeBase:
    armor: dict[str, int] = field(default_factory=dict)

    @property
    def total_armor(self) -> int:
        return sum(self.armor.values())


@dataclass(eq=False)
class FakeCp:
    name: str
    captured: Player
    x: float = 0.0
    armor: int = 0
    has_active_frontline: bool = False
    can_deploy_ground_units: bool = True
    connected_points: list[Any] = field(default_factory=list)
    squadrons: list[FakeSquadron] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = self.name
        self.ground_unit_orders = RecordingOrders()
        self.base = FakeBase({TANK: self.armor} if self.armor else {})
        self.position = SimpleNamespace(
            distance_to_point=lambda other: abs(self.x - other.x), x=self.x
        )


class RecordingTransfers:
    def __init__(self) -> None:
        self.created: list[Any] = []

    def new_transfer(self, transfer: Any, now: Any) -> None:
        self.created.append(transfer)

    def __iter__(self) -> Any:
        return iter(self.created)


def make_game(
    cps: list[FakeCp],
    red_network: TransitNetwork | None = None,
    frontline_units: tuple[FakeUnit, ...] = (),
    budget: float = 0,
) -> Any:
    red_network = red_network if red_network is not None else TransitNetwork()
    blue_network = TransitNetwork()
    red = SimpleNamespace(
        transit_network=red_network,
        transfers=RecordingTransfers(),
        procurement_requests=set(),
        faction=SimpleNamespace(frontline_units=set(frontline_units)),
        budget=budget,
    )

    def adjust_budget(amount: float) -> None:
        red.budget += amount

    red.adjust_budget = adjust_budget
    game = SimpleNamespace(
        settings=None,
        red=red,
        theater=SimpleNamespace(controlpoints=cps),
        bluefor_mission_history=SimpleNamespace(),
    )
    game.transit_network_for = lambda player: (
        red_network if player is Player.RED else blue_network
    )
    return game


def road(network: TransitNetwork, a: FakeCp, b: FakeCp) -> None:
    network.link_with(a, b, TransitConnection.Road)  # type: ignore[arg-type]


def test_supply_planner_moves_units_between_red_bases() -> None:
    a = FakeCp("A", Player.RED, x=0, armor=8)
    b = FakeCp("B", Player.RED, x=10_000, armor=0)
    network = TransitNetwork()
    road(network, a, b)
    game = make_game([a, b], network)

    RedforSupplyPlanner(game).plan()

    created = game.red.transfers.created
    assert len(created) == 1, "old truthiness bug planned nothing at all"
    assert {created[0].origin, created[0].destination} == {a, b}


def test_supply_planner_ignores_blue_and_neutral_bases() -> None:
    red = FakeCp("R", Player.RED, x=0, armor=8)
    blue = FakeCp("B", Player.BLUE, x=10_000, armor=8)
    neutral = FakeCp("N", Player.NEUTRAL, x=20_000, armor=8)
    network = TransitNetwork()
    road(network, red, blue)
    road(network, red, neutral)
    game = make_game([red, blue, neutral], network)

    RedforSupplyPlanner(game).plan()

    assert game.red.transfers.created == []


def test_supply_planner_has_no_neutral_capture_path() -> None:
    # Ground transfers can never reach a neutral CP (it is in no coalition's
    # transit network), so the dead _plan_neutral_captures() was removed.
    # Neutral bases are taken by the AI commander's air assaults instead.
    assert not hasattr(RedforSupplyPlanner, "_plan_neutral_captures")


def test_has_transfer_route() -> None:
    a: Any = FakeCp("A", Player.RED)
    b: Any = FakeCp("B", Player.RED)
    c: Any = FakeCp("C", Player.RED)
    island: Any = FakeCp("I", Player.RED)
    network = TransitNetwork()
    road(network, a, b)
    road(network, b, c)
    game = make_game([a, b, c, island], network)

    assert has_transfer_route(game, a, c)
    assert not has_transfer_route(game, a, island)


def test_counter_cas_reinforces_red_front_from_red_rear() -> None:
    front = FakeCp("Front", Player.RED, armor=2, has_active_frontline=True)
    rear = FakeCp("Rear", Player.RED, armor=12)
    blue_rear = FakeCp("BlueRear", Player.BLUE, armor=12)
    network = TransitNetwork()
    road(network, front, rear)
    game = make_game([front, rear, blue_rear], network)

    RedforAdaptivePlanner(game)._counter_cas(count=3)

    created = game.red.transfers.created
    assert len(created) == 1, "old truthiness bug skipped every control point"
    assert created[0].origin is rear and created[0].destination is front


def test_counter_cas_skips_rear_base_with_no_route() -> None:
    front = FakeCp("Front", Player.RED, armor=2, has_active_frontline=True)
    cut_off = FakeCp("CutOff", Player.RED, armor=12)
    game = make_game([front, cut_off], TransitNetwork())

    RedforAdaptivePlanner(game)._counter_cas(count=3)

    assert game.red.transfers.created == []


def test_counter_sead_buys_cheapest_shorad_for_red_front() -> None:
    front_a = FakeCp("FrontA", Player.RED, has_active_frontline=True)
    front_b = FakeCp("FrontB", Player.RED, has_active_frontline=True)
    front_c = FakeCp("FrontC", Player.RED, has_active_frontline=True)
    rear = FakeCp("Rear", Player.RED)
    blue_front = FakeCp("BlueFront", Player.BLUE, has_active_frontline=True)
    game = make_game(
        [blue_front, front_a, rear, front_b, front_c],
        frontline_units=(SHILKA, STRELA, TUNGUSKA, T72),
        budget=100,
    )

    # Used to raise ImportError (GroundUnitProcurementRequest does not exist).
    RedforAdaptivePlanner(game)._counter_sead(count=4)

    assert front_a.ground_unit_orders.units == {STRELA: 1}
    assert front_b.ground_unit_orders.units == {STRELA: 1}
    assert front_c.ground_unit_orders.units == {}, "capped at 2 per turn"
    assert rear.ground_unit_orders.units == {}
    assert blue_front.ground_unit_orders.units == {}
    assert game.red.budget == 100 - 2 * STRELA.price


def test_counter_sead_falls_back_to_aaa_and_respects_budget() -> None:
    front = FakeCp("Front", Player.RED, has_active_frontline=True)
    game = make_game([front], frontline_units=(SHILKA, T72), budget=5)

    RedforAdaptivePlanner(game)._counter_sead(count=2)
    assert front.ground_unit_orders.units == {}, "Shilka costs 6, budget is 5"
    assert game.red.budget == 5

    game.red.budget = 10
    RedforAdaptivePlanner(game)._counter_sead(count=2)
    assert front.ground_unit_orders.units == {SHILKA: 1}
    assert game.red.budget == 4


def test_counter_sead_without_air_defence_units_does_nothing() -> None:
    front = FakeCp("Front", Player.RED, has_active_frontline=True)
    game = make_game([front], frontline_units=(T72,), budget=100)

    RedforAdaptivePlanner(game)._counter_sead(count=5)

    assert front.ground_unit_orders.units == {}
    assert game.red.budget == 100


def test_counter_oca_request_survives_the_turn_boundary() -> None:
    base = FakeCp("Airbase", Player.RED, squadrons=[FakeSquadron({FlightType.BARCAP})])
    game = make_game([base])
    game.redfor_pending_procurement_requests = []

    RedforAdaptivePlanner(game)._counter_oca(count=3)

    expected = AircraftProcurementRequest(base, FlightType.BARCAP, 2)  # type: ignore[arg-type]
    assert game.redfor_pending_procurement_requests == [expected]

    # Coalition.initialize_turn() clears procurement_requests, then restores.
    red: Any = SimpleNamespace(player=Player.RED, game=game, procurement_requests=set())
    Coalition.restore_redfor_adaptive_requests(red)
    assert red.procurement_requests == {expected}
    assert game.redfor_pending_procurement_requests == []


def test_blue_coalition_does_not_take_red_requests() -> None:
    game = SimpleNamespace(redfor_pending_procurement_requests=["request"])
    blue: Any = SimpleNamespace(
        player=Player.BLUE, game=game, procurement_requests=set()
    )

    Coalition.restore_redfor_adaptive_requests(blue)

    assert blue.procurement_requests == set()
    assert game.redfor_pending_procurement_requests == ["request"]
