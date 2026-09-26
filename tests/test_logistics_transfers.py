"""Warehouse transfers carried by LOGISTIC flights.

Covers LogisticsManager.on_turn_end / on_state_processed (the two gameloop
hooks that did not exist) and the flight helpers in transfer_flights. Planning
a real flight and generating a real .miz are verified end to end separately.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from game.ato.flighttype import FlightType
from game.logistics import (
    LogisticsManager,
    StockItem,
    TransferStatus,
    Warehouse,
    WarehouseCategory,
)
from game.logistics import transfer_flights
from game.theater.player import Player

FUEL = WarehouseCategory.FUEL


class FakeCp:
    def __init__(
        self,
        name: str,
        x: float = 0,
        owner: Player = Player.BLUE,
        runway: bool = True,
    ) -> None:
        self.id = name
        self.name = name
        self.captured = owner
        self.runway = runway
        self.position = SimpleNamespace(
            x=x, distance_to_point=lambda other: abs(x - other.x)
        )

    def can_operate(self, aircraft: Any) -> bool:
        return self.runway or aircraft.dcs_unit_type.helicopter


class FakeFlight:
    def __init__(self, transfer_id: Optional[str], count: int = 1) -> None:
        self.id = uuid.uuid4()
        self.transfer_id = transfer_id
        self.count = count
        self.package: Any = None


class FakePackage:
    def __init__(self, *flights: FakeFlight) -> None:
        self.flights = list(flights)
        for flight in flights:
            flight.package = self

    def remove_flight(self, flight: FakeFlight) -> None:
        self.flights.remove(flight)


class FakeAto:
    def __init__(self) -> None:
        self.packages: list[FakePackage] = []

    def remove_package(self, package: FakePackage) -> None:
        self.packages.remove(package)


def _theater(*cps: FakeCp) -> Any:
    by_id = {cp.id: cp for cp in cps}

    def find(cp_id: Any) -> FakeCp:
        if cp_id not in by_id:
            raise KeyError(cp_id)
        return by_id[cp_id]

    return SimpleNamespace(find_control_point_by_id=find, controlpoints=list(cps))


def _warehouse(cp: FakeCp, fuel: float, capacity: float = 1000.0) -> Warehouse:
    wh = Warehouse(cp_id=cp.id, cp_name=cp.name)  # type: ignore[arg-type]
    wh.stock[FUEL] = StockItem(quantity=fuel, capacity=capacity)
    return wh


class Setup:
    """Two friendly bases with warehouses and one scheduled fuel transfer."""

    def __init__(self, quantity: float = 250, dest_fuel: float = 100) -> None:
        self.source = FakeCp("Source", x=0)
        self.dest = FakeCp("Dest", x=50_000)
        self.lm = LogisticsManager()
        self.lm.add_warehouse(_warehouse(self.source, 500))
        self.lm.add_warehouse(_warehouse(self.dest, dest_fuel))
        self.ato = FakeAto()
        self.game: Any = SimpleNamespace(
            turn=3,
            logistics=self.lm,
            theater=_theater(self.source, self.dest),
            blue=SimpleNamespace(ato=self.ato),
        )
        transfer = self.lm.schedule_transfer(
            self.source.id, self.dest.id, "", FUEL, quantity, "UH-60A", 3  # type: ignore[arg-type]
        )
        assert transfer is not None
        self.transfer = transfer
        self.flight = FakeFlight(transfer.transfer_id, count=2)

    def fuel(self, cp: FakeCp) -> float:
        wh = self.lm.get_warehouse(cp.id)  # type: ignore[arg-type]
        assert wh is not None
        return wh.stock[FUEL].quantity

    def put_flight_in_ato(self) -> None:
        self.ato.packages.append(FakePackage(self.flight))

    def debrief(self, lost: int = 0) -> Any:
        flight = self.flight

        def surviving(f: Any) -> int:
            return f.count - (lost if f is flight else 0)

        return SimpleNamespace(
            air_losses=SimpleNamespace(surviving_flight_members=surviving)
        )

    def fly(self, lost: int = 0) -> list[str]:
        self.put_flight_in_ato()
        self.lm.on_turn_end(self.game)
        assert self.transfer.status is TransferStatus.IN_FLIGHT
        return self.lm.on_state_processed(self.game, self.debrief(lost))


# --- on_turn_end -----------------------------------------------------------------


def test_scheduling_takes_the_stock_from_the_source() -> None:
    s = Setup()
    assert s.fuel(s.source) == 250
    assert s.transfer.status is TransferStatus.PLANNED


def test_transfer_with_a_flight_goes_in_flight() -> None:
    s = Setup()
    s.put_flight_in_ato()
    s.lm.on_turn_end(s.game)
    assert s.transfer.status is TransferStatus.IN_FLIGHT


def test_transfer_without_a_flight_stays_planned() -> None:
    s = Setup()
    s.lm.on_turn_end(s.game)
    assert s.transfer.status is TransferStatus.PLANNED


def test_attrition_is_one_percent_once_per_turn() -> None:
    s = Setup()
    s.lm.on_turn_end(s.game)
    s.lm.on_turn_end(s.game)  # mission regenerated in the same turn
    assert s.fuel(s.source) == pytest.approx(250 * 0.99)
    assert s.fuel(s.dest) == pytest.approx(100 * 0.99)

    s.game.turn += 1
    s.lm.on_turn_end(s.game)
    assert s.fuel(s.source) == pytest.approx(250 * 0.99 * 0.99)


def test_attrition_works_on_saves_from_before_it_existed() -> None:
    s = Setup()
    del s.lm._last_attrition_turn  # pickled before the attribute existed
    s.lm.on_turn_end(s.game)
    assert s.fuel(s.source) == pytest.approx(250 * 0.99)


# --- on_state_processed ------------------------------------------------------------


def test_surviving_flight_delivers_the_cargo() -> None:
    s = Setup(quantity=250, dest_fuel=100)
    log = s.fly(lost=1)  # one of two aircraft lost: still delivered

    assert s.transfer.status is TransferStatus.DELIVERED
    assert s.transfer.delivered == 250
    assert s.fuel(s.dest) == pytest.approx(100 * 0.99 + 250)
    assert "250 fuel delivered to Dest" in log[0]


def test_overflow_returns_to_the_source() -> None:
    s = Setup(quantity=250, dest_fuel=900)
    log = s.fly()

    room = 1000 - 900 * 0.99
    assert s.transfer.delivered == pytest.approx(room)
    assert s.fuel(s.dest) == pytest.approx(1000)
    assert s.fuel(s.source) == pytest.approx(250 * 0.99 + (250 - room))
    assert "returned to Source (no room)" in log[0]


def test_whole_flight_shot_down_loses_the_cargo() -> None:
    s = Setup()
    log = s.fly(lost=2)

    assert s.transfer.status is TransferStatus.FAILED
    assert s.fuel(s.dest) == pytest.approx(100 * 0.99)
    assert s.fuel(s.source) == pytest.approx(250 * 0.99)
    assert "flight lost" in log[0]


@pytest.mark.parametrize("which", ["source", "dest"])
def test_base_changing_hands_loses_the_cargo(which: str) -> None:
    s = Setup()
    s.put_flight_in_ato()
    s.lm.on_turn_end(s.game)
    getattr(s, which).captured = Player.RED

    log = s.lm.on_state_processed(s.game, s.debrief())

    assert s.transfer.status is TransferStatus.FAILED
    assert s.fuel(s.dest) == pytest.approx(100 * 0.99)
    assert "base changed hands" in log[0]


def test_flight_removed_mid_turn_goes_back_to_planned() -> None:
    s = Setup()
    s.put_flight_in_ato()
    s.lm.on_turn_end(s.game)
    s.ato.packages.clear()

    assert s.lm.on_state_processed(s.game, s.debrief()) == []
    assert s.transfer.status is TransferStatus.PLANNED


# --- transfer_flights helpers ------------------------------------------------------


def test_flight_for_transfer_finds_the_flight() -> None:
    s = Setup()
    s.ato.packages.append(FakePackage(FakeFlight(None), FakeFlight("other")))
    s.put_flight_in_ato()
    assert (
        transfer_flights.flight_for_transfer(s.game, s.transfer.transfer_id) is s.flight
    )
    assert transfer_flights.flight_for_transfer(s.game, "missing") is None


def test_remove_transfer_flight_drops_the_empty_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("game.server.EventStream.put_nowait", lambda events: None)
    s = Setup()
    s.put_flight_in_ato()

    assert transfer_flights.remove_transfer_flight(s.game, s.transfer.transfer_id)
    assert s.ato.packages == []
    assert not transfer_flights.remove_transfer_flight(s.game, s.transfer.transfer_id)


def _squadron(
    name: str,
    base: FakeCp,
    free: bool = True,
    logistic: bool = True,
    helicopter: bool = False,
    flyable: bool = True,
) -> Any:
    return SimpleNamespace(
        name=name,
        location=base,
        aircraft=SimpleNamespace(
            dcs_unit_type=SimpleNamespace(helicopter=helicopter), flyable=flyable
        ),
        capable_of=lambda task: logistic and task is FlightType.LOGISTIC,
        can_fulfill_flight=lambda count: free,
    )


def _air_wing_game(*squadrons: Any, **extra: Any) -> Any:
    return SimpleNamespace(
        blue=SimpleNamespace(
            air_wing=SimpleNamespace(iter_squadrons=lambda: list(squadrons)),
            ato=FakeAto(),
        ),
        **extra,
    )


def test_squadron_list_offers_every_free_capable_one_nearest_first() -> None:
    source = FakeCp("Source", x=0)
    dest = FakeCp("Dest", x=100)
    busy = _squadron("busy", FakeCp("A", x=10), free=False)
    fighter = _squadron("fighter", FakeCp("B", x=20), logistic=False)
    enemy_base = _squadron("enemy", FakeCp("C", x=30, owner=Player.RED))
    ai_only = _squadron("C-17A", FakeCp("F", x=5), flyable=False)
    near = _squadron("near", FakeCp("D", x=40))
    far = _squadron("far", FakeCp("E", x=90))
    game = _air_wing_game(far, busy, fighter, enemy_base, ai_only, near)

    offered = transfer_flights.transport_squadrons(game, source, dest)  # type: ignore[arg-type]

    assert [s.name for s in offered] == ["near", "far"]


def test_only_helicopters_are_offered_for_a_farp() -> None:
    source = FakeCp("Source", x=0)
    farp = FakeCp("FARP", x=50, runway=False)
    plane = _squadron("C-130", FakeCp("A", x=10))
    helo = _squadron("UH-60A", FakeCp("B", x=20), helicopter=True)
    game = _air_wing_game(plane, helo)

    offered = transfer_flights.transport_squadrons(game, source, farp)  # type: ignore[arg-type]

    assert [s.name for s in offered] == ["UH-60A"]


def _pending_transfer(squadrons: list[Any]) -> tuple[Any, Any]:
    s = Setup()
    game = _air_wing_game(*squadrons, theater=s.game.theater, logistics=s.lm)
    return game, s.transfer


def test_no_squadron_picked_means_no_flight() -> None:
    game, transfer = _pending_transfer([_squadron("sq", FakeCp("A"))])
    assert transfer_flights.plan_transfer_flight(game, transfer, now=None) is None  # type: ignore[arg-type]


def test_picked_squadron_is_remembered_for_next_turn() -> None:
    busy = _squadron("busy", FakeCp("A"), free=False)
    game, transfer = _pending_transfer([busy])

    flight = transfer_flights.plan_transfer_flight(
        game, transfer, now=None, squadron=busy  # type: ignore[arg-type]
    )

    assert flight is None, "the picked squadron has no free aircraft this turn"
    assert transfer.squadron is busy, "retried with the same squadron next turn"


def test_turn_start_retries_unsettled_transfers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = Setup()
    stale = s.lm.schedule_transfer(s.source.id, s.dest.id, "", FUEL, 10, "x", 2)  # type: ignore[arg-type]
    assert stale is not None
    stale.status = TransferStatus.IN_FLIGHT  # results never processed
    done = s.lm.schedule_transfer(s.source.id, s.dest.id, "", FUEL, 10, "x", 2)  # type: ignore[arg-type]
    assert done is not None
    done.status = TransferStatus.DELIVERED

    planned: list[str] = []
    monkeypatch.setattr(
        transfer_flights,
        "plan_transfer_flight",
        lambda game, t, now: planned.append(t.transfer_id),
    )
    transfer_flights.plan_pending_transfer_flights(s.game, now=None)  # type: ignore[arg-type]

    assert sorted(planned) == sorted([s.transfer.transfer_id, stale.transfer_id])
    assert stale.status is TransferStatus.PLANNED
    assert done.status is TransferStatus.DELIVERED
