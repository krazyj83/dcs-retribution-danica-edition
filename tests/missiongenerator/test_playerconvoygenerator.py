"""Player-drawn convoys borrow real vehicles and settle them after the mission.

Generation runs against a real pydcs Mission on the Caucasus terrain and a real
UnitMap; settlement runs the real Debriefing loss sorting and
MissionResultsProcessor.commit_player_drawn_convoys.
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from dcs.mapping import LatLng, Point
from dcs.mission import Mission
from dcs.point import PointAction
from dcs.terrain import Caucasus
from dcs.vehicles import vehicle_map

from game.dcs.groundunittype import GroundUnitType
from game.debriefing import Debriefing
from game.missiongenerator.playerconvoygenerator import (
    CONVOY_SIZE,
    PlayerConvoyGenerator,
)
from game.server.convoyroutes import routes as convoy_routes
from game.sim.missionresultsprocessor import MissionResultsProcessor
from game.theater.player import Player
from game.theater.theatergroundobject import MotorpoolGroundObject
from game.unitmap import UnitMap

TERRAIN = Caucasus()

# Near Kutaisi: the route runs west to east.
ROUTE_START = SimpleNamespace(lat=42.176, lng=42.482)
ROUTE_END = SimpleNamespace(lat=42.250, lng=42.700)


def _unit(dcs_name: str) -> GroundUnitType:
    return next(GroundUnitType.for_dcs_type(vehicle_map[dcs_name]))


ABRAMS = _unit("M-1 Abrams")
BRADLEY = _unit("M-2 Bradley")
TRUCK = _unit("M 818")


def _at(lat: float, lng: float) -> Point:
    return Point.from_latlng(LatLng(lat, lng), TERRAIN)


class FakeBase:
    def __init__(self, armor: dict[GroundUnitType, int]) -> None:
        self.armor = dict(armor)

    def total_units_of_type(self, unit_type: GroundUnitType) -> int:
        return self.armor.get(unit_type, 0)

    def commission_units(self, units: dict[GroundUnitType, int]) -> None:
        for unit_type, count in units.items():
            self.armor[unit_type] = self.armor.get(unit_type, 0) + count


class FakeCp:
    def __init__(
        self,
        name: str,
        position: Point,
        armor: dict[GroundUnitType, int],
        owner: Player = Player.BLUE,
    ) -> None:
        self.name = name
        self.position = position
        self.base = FakeBase(armor)
        self.captured = owner
        self.can_deploy_ground_units = True
        self.connected_points: list[Any] = []  # no enemy: all armor is reserve
        self.ground_objects: list[Any] = []

    def __str__(self) -> str:
        return self.name


def _game(cps: list[FakeCp]) -> Any:
    faction = SimpleNamespace(
        name="Test faction",
        country=SimpleNamespace(name="USA"),
        liveries_overrides={},
    )
    return SimpleNamespace(
        theater=SimpleNamespace(terrain=TERRAIN, controlpoints=cps),
        coalition_for=lambda player: SimpleNamespace(faction=faction),
    )


def _route(name: str = "Supply Road") -> Any:
    return SimpleNamespace(name=name, start=ROUTE_START, end=ROUTE_END)


def _generate(
    cps: list[FakeCp], routes: list[Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[Mission, UnitMap]:
    monkeypatch.setattr(convoy_routes, "get_all", lambda: routes)
    mission = Mission(TERRAIN)
    unit_map = UnitMap()
    PlayerConvoyGenerator(mission, _game(cps), unit_map).generate()
    return mission, unit_map


def _near_start(name: str, armor: dict[GroundUnitType, int], **kw: Any) -> FakeCp:
    return FakeCp(name, _at(42.170, 42.470), armor, **kw)


def _near_end(name: str, armor: dict[GroundUnitType, int], **kw: Any) -> FakeCp:
    return FakeCp(name, _at(42.260, 42.710), armor, **kw)


def _far_away(name: str, armor: dict[GroundUnitType, int], **kw: Any) -> FakeCp:
    return FakeCp(name, _at(41.600, 41.600), armor, **kw)


def _types(unit_map: UnitMap) -> Counter[GroundUnitType]:
    return Counter(u.unit_type for u in unit_map.player_drawn_convoys.values())


# --- Generation --------------------------------------------------------------


def test_convoy_is_a_mixed_group_from_the_base_nearest_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _near_start("Source", {TRUCK: 10, BRADLEY: 3, ABRAMS: 1})
    delivery = _near_end("Delivery", {})
    far = _far_away("Far", {TRUCK: 50})
    mission, unit_map = _generate([far, delivery, source], [_route()], monkeypatch)

    groups = mission.country("USA").vehicle_group
    assert len(groups) == 1
    group = groups[0]
    assert group.name == "Player Convoy 1 - Supply Road"
    assert len(group.units) == CONVOY_SIZE
    # Round-robin over the most plentiful types.
    assert _types(unit_map) == Counter({TRUCK: 2, BRADLEY: 1, ABRAMS: 1})
    # Each DCS unit is mapped to its own type, in order.
    for unit in group.units:
        mapped = unit_map.player_drawn_convoy_unit(str(unit.name))
        assert mapped is not None
        assert unit.type == mapped.unit_type.dcs_unit_type.id
        assert mapped.origin is source and mapped.destination is delivery
    assert all(u.player_can_drive for u in group.units)
    assert [p.action for p in group.points] == [PointAction.OnRoad] * 2
    # Generation borrows; nothing leaves the base until the mission is settled.
    assert source.base.armor == {TRUCK: 10, BRADLEY: 3, ABRAMS: 1}


def test_falls_back_to_the_next_nearest_base_with_spare_vehicles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _near_start("Empty", {})
    far = _far_away("Far", {TRUCK: 6})
    _, unit_map = _generate([empty, far], [_route()], monkeypatch)

    origins = {u.origin for u in unit_map.player_drawn_convoys.values()}
    assert origins == {far}


def test_no_spare_vehicles_anywhere_skips_the_convoy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission, unit_map = _generate(
        [_near_start("Empty", {}), _near_end("AlsoEmpty", {})], [_route()], monkeypatch
    )
    assert mission.country("USA").vehicle_group == []
    assert unit_map.player_drawn_convoys == {}


def test_small_reserve_gives_a_smaller_convoy(monkeypatch: pytest.MonkeyPatch) -> None:
    _, unit_map = _generate(
        [_near_start("Small", {ABRAMS: 2})], [_route()], monkeypatch
    )
    assert _types(unit_map) == Counter({ABRAMS: 2})


def test_enemy_bases_are_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    red = _near_start("Red", {TRUCK: 10}, owner=Player.RED)
    blue = _far_away("Blue", {TRUCK: 10})
    _, unit_map = _generate([red, blue], [_route()], monkeypatch)
    assert {u.origin for u in unit_map.player_drawn_convoys.values()} == {blue}


def test_two_convoys_never_take_the_same_vehicle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    near = _near_start("Near", {TRUCK: 5})
    far = _far_away("Far", {BRADLEY: 4})
    _, unit_map = _generate(
        [near, far], [_route("North"), _route("South")], monkeypatch
    )

    by_origin = Counter(u.origin.name for u in unit_map.player_drawn_convoys.values())
    # First convoy takes 4 of Near's 5 trucks; the second gets the last truck.
    assert by_origin == Counter({"Near": 5})


def test_vehicles_parked_in_a_motorpool_are_not_spare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _near_start("Source", {ABRAMS: 3, TRUCK: 1})
    motorpool = MotorpoolGroundObject.__new__(MotorpoolGroundObject)
    motorpool.groups = [SimpleNamespace(id=7, units=[object(), object(), object()])]  # type: ignore[list-item]
    motorpool.motorpool_unit_types = {7: ABRAMS}
    source.ground_objects = [motorpool]

    _, unit_map = _generate([source], [_route()], monkeypatch)

    assert _types(unit_map) == Counter({TRUCK: 1})


# --- Settlement after the mission ----------------------------------------------


def _debrief(unit_map: UnitMap, killed: list[str]) -> Debriefing:
    debriefing = Debriefing.__new__(Debriefing)
    debriefing.unit_map = unit_map
    debriefing.state_data = SimpleNamespace(  # type: ignore[assignment]
        killed_ground_units=killed, killed_aircraft=[]
    )
    debriefing.ground_losses = debriefing.dead_ground_units()
    return debriefing


def test_dead_vehicles_are_lost_and_survivors_are_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _near_start("Source", {TRUCK: 10, BRADLEY: 3, ABRAMS: 1})
    delivery = _near_end("Delivery", {ABRAMS: 5})
    mission, unit_map = _generate([source, delivery], [_route()], monkeypatch)
    group = mission.country("USA").vehicle_group[0]
    abrams_name = next(
        str(u.name) for u in group.units if u.type == ABRAMS.dcs_unit_type.id
    )

    debriefing = _debrief(unit_map, killed=[abrams_name])
    assert [u.unit_type for u in debriefing.player_drawn_convoy_losses] == [ABRAMS]
    assert debriefing.player_drawn_convoy_losses_by_type(Player.BLUE) == {ABRAMS: 1}

    MissionResultsProcessor.commit_player_drawn_convoys(debriefing)

    # Lost: 1 Abrams. Delivered: 2 trucks + 1 Bradley.
    assert source.base.armor == {TRUCK: 8, BRADLEY: 2, ABRAMS: 0}
    assert delivery.base.armor == {ABRAMS: 5, TRUCK: 2, BRADLEY: 1}


def test_survivors_stay_home_if_the_delivery_base_changed_hands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _near_start("Source", {TRUCK: 4})
    delivery = _near_end("Delivery", {})
    _, unit_map = _generate([source, delivery], [_route()], monkeypatch)
    delivery.captured = Player.RED

    MissionResultsProcessor.commit_player_drawn_convoys(_debrief(unit_map, []))

    assert source.base.armor == {TRUCK: 4}
    assert delivery.base.armor == {}


def test_route_ending_at_its_own_source_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    only = _near_start("Only", {TRUCK: 4})
    _, unit_map = _generate([only], [_route()], monkeypatch)

    MissionResultsProcessor.commit_player_drawn_convoys(_debrief(unit_map, []))

    assert only.base.armor == {TRUCK: 4}
