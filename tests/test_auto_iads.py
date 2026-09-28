"""Automatic advanced IADS: clustering, spot search and when it applies."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dcs.mapping import Point
from dcs.terrain import Caucasus

from game.theater.iadsnetwork import autoiads
from game.theater.iadsnetwork.iadsnetwork import IadsNetwork
from game.theater.player import Player
from game.theater.start_generator import auto_iads_active

TERRAIN = Caucasus()


def _p(x: float, y: float) -> Point:
    return Point(x, y, TERRAIN)


def test_sites_close_together_share_a_cluster() -> None:
    sites = [_p(0, 0), _p(5_000, 0), _p(11_000, 0), _p(40_000, 0), _p(45_000, 0)]

    groups = autoiads.cluster(sites, lambda p: p, autoiads.CLUSTER_RADIUS_M)

    assert [len(g) for g in groups] == [3, 2]


def test_tower_at_the_cluster_centre_reaches_every_site() -> None:
    # Worst case: sites at opposite edges of the cluster radius.
    sites = [_p(0, 0), _p(12_000, 0), _p(-12_000, 0), _p(0, 12_000)]
    groups = autoiads.cluster(sites, lambda p: p, autoiads.CLUSTER_RADIUS_M)
    assert len(groups) == 1
    centre = autoiads.centroid(groups[0])
    comms_range = 27_780
    assert all(centre.distance_to_point(s) < comms_range for s in sites)


def test_spot_avoids_the_base_objects_and_water() -> None:
    base = _p(0, 0)
    blocked = [_p(3_000, 0)]
    water_east = lambda p: p.x < 2_500  # everything east of x=2.5 km is sea

    spot = autoiads.find_spot(_p(3_000, 0), base, blocked, water_east)

    assert spot is not None
    assert spot.distance_to_point(base) >= autoiads.MIN_DISTANCE_FROM_BASE_M
    assert spot.distance_to_point(blocked[0]) >= autoiads.MIN_DISTANCE_FROM_OBJECTS_M
    assert spot.x < 2_500


def test_spot_must_stay_within_reach_of_the_sites() -> None:
    sites = [_p(20_000, 0)]
    spot = autoiads.find_spot(
        _p(20_000, 0), _p(0, 0), [], lambda p: True, reach=sites, reach_m=1_000
    )
    assert spot is not None and spot.distance_to_point(sites[0]) <= 1_000

    nowhere = autoiads.find_spot(_p(0, 0), _p(0, 0), [], lambda p: False)
    assert nowhere is None


def _cp(side: Player, x: float) -> Any:
    return SimpleNamespace(captured=side, position=_p(x, 0))


def test_enemy_distance_ignores_friends_and_neutrals() -> None:
    home = _cp(Player.BLUE, 0)
    points = [
        home,
        _cp(Player.BLUE, 10_000),
        _cp(Player.NEUTRAL, 20_000),
        _cp(Player.RED, 50_000),
        _cp(Player.RED, 80_000),
    ]
    assert autoiads.enemy_distance(home, points) == 50_000


def _game(auto: bool, config: list[Any], placed: bool = False) -> Any:
    presets = SimpleNamespace(
        iads_command_center=[],
        iads_connection_node=["tower"] if placed else [],
        iads_power_source=[],
    )
    return SimpleNamespace(
        settings=SimpleNamespace(advanced_iads_auto=auto),
        theater=SimpleNamespace(
            iads_network=IadsNetwork(False, config),
            controlpoints=[SimpleNamespace(preset_locations=presets)],
        ),
    )


def test_auto_iads_only_when_the_author_did_not_set_it_up() -> None:
    assert auto_iads_active(_game(True, []))
    assert not auto_iads_active(_game(False, []))
    assert not auto_iads_active(_game(True, ["SAM-1"]))  # iads_config
    assert not auto_iads_active(_game(True, [], placed=True))  # buildings in miz
