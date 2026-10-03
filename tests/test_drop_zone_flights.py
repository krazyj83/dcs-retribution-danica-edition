"""Transport flights planned without cargo, and transport and logistic flights
to a player drop zone (game/ato/flightplans/airlift.py, logistic.py and
game/logistics/flight_cargo.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from dcs.helicopters import CH_47Fbl1
from dcs.mapping import Point
from dcs.terrain import Caucasus

from game.ato.flightplans.airlift import Builder as AirliftBuilder
from game.ato.flightplans.airlift import is_base
from game.ato.flightplans.planningerror import PlanningError
from game.logistics import DropZone, DropZoneType, LogisticsManager
from game.logistics.custom_airdrop import CustomAirdropTarget
from game.logistics.flight_cargo import attach_transfer, drop_zone_base
from game.theater.player import Player
from tests.test_logistics_transfers import FakeCp, _theater

TERRAIN = Caucasus()


def _cp(name: str, x: float, owner: Player = Player.BLUE) -> FakeCp:
    cp = FakeCp(name, x=x, owner=owner)
    cp.is_fleet = False  # type: ignore[attr-defined]
    return cp


@pytest.fixture
def fake_cps_are_control_points(monkeypatch: pytest.MonkeyPatch) -> None:
    import game.theater

    monkeypatch.setattr(game.theater, "ControlPoint", FakeCp)


class Setup:
    """Home base at x=0, a friendly base at x=40 km, an enemy base at x=60 km,
    and a drop zone at x=50 km that the old map code gave to the enemy base."""

    def __init__(self) -> None:
        origin = Point(0, 0, TERRAIN)
        self.home = _cp("Home", 0)
        self.forward = _cp("Forward", 40_000)
        self.enemy = _cp("Enemy", 60_000, owner=Player.RED)
        self.lm = LogisticsManager()
        dz_point = Point(origin.x + 50_000, origin.y, TERRAIN)
        ll = dz_point.latlng()
        self.dz = DropZone(
            name="DZ Hawk",
            dz_type=DropZoneType.CARGO,
            lat=ll.lat,
            lon=ll.lng,
            cp_id=self.enemy.id,  # type: ignore[arg-type]
            coalition="red",
            cp_name="Enemy",
            dz_id="dz-hawk",
        )
        self.lm.add_drop_zone(self.dz)
        theater = _theater(self.home, self.forward, self.enemy)
        theater.terrain = TERRAIN
        self.game: Any = SimpleNamespace(turn=2, logistics=self.lm, theater=theater)
        self.target = CustomAirdropTarget(
            name="DZ Hawk", position=dz_point, dz_id="dz-hawk"
        )

    def flight(self, target: Any) -> Any:
        return SimpleNamespace(
            transfer_id=None,
            departure=self.home,
            arrival=self.home,
            package=SimpleNamespace(target=target),
            squadron=SimpleNamespace(player=Player.BLUE),
            unit_type=SimpleNamespace(dcs_unit_type=CH_47Fbl1),
            fuel=CH_47Fbl1.fuel_max,
            cargo=None,
        )


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_a_logistic_flight_to_a_drop_zone_supplies_its_friendly_base() -> None:
    s = Setup()
    t = attach_transfer(s.game, s.flight(s.target))
    assert (t.source_cp_id, t.dest_cp_id, t.dz_id) == ("Home", "Forward", "dz-hawk")
    # The drop zone moved over from the enemy base, so the crates set down
    # in it are credited to Forward (crate_delivery counts a base's own zones).
    assert (s.dz.cp_id, s.dz.cp_name, s.dz.coalition) == ("Forward", "Forward", "blue")


def test_a_drop_zone_of_a_friendly_base_keeps_its_base() -> None:
    s = Setup()
    s.dz.cp_id = s.home.id  # type: ignore[assignment]
    assert drop_zone_base(s.game, s.dz) is s.home


def test_no_friendly_base_means_no_base() -> None:
    s = Setup()
    for cp in (s.home, s.forward):
        cp.captured = Player.RED
    assert drop_zone_base(s.game, s.dz) is None


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_a_deleted_drop_zone_cannot_be_supplied() -> None:
    s = Setup()
    s.lm.remove_drop_zone("dz-hawk")
    with pytest.raises(PlanningError, match="no longer exists"):
        attach_transfer(s.game, s.flight(s.target))


@pytest.mark.usefixtures("fake_cps_are_control_points")
def test_logistic_flights_to_a_friendly_base_still_work() -> None:
    s = Setup()
    t = attach_transfer(s.game, s.flight(s.forward))
    assert (t.dest_cp_id, t.dz_id) == ("Forward", "")


def test_a_transport_without_cargo_flies_empty_to_its_target() -> None:
    s = Setup()
    builder = object.__new__(AirliftBuilder)
    builder.flight = s.flight(s.target)
    stops = builder.cargo_stops()
    assert stops.origin is s.home and stops.next_stop is s.target
    assert not is_base(s.target)
    # No CTLD at a drop zone: the crew drops off at the drop zone itself.
    assert builder._generate_ctld_dropoff() == s.target.position


def test_drop_zone_targets_offer_transport_and_logistic() -> None:
    from game.ato.flighttype import FlightType

    types = set(Setup().target.mission_types(Player.BLUE))
    assert {FlightType.TRANSPORT, FlightType.LOGISTIC} <= types
