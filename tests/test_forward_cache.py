"""Forward caches (game/logistics/forward_cache.py): crates left in a drop zone
stay there between missions until carried to a base or destroyed."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from dcs import Mission
from dcs.mapping import Point
from dcs.terrain import Caucasus
from dcs.weapons_data import Weapons

from game.logistics import (
    DropZone,
    DropZoneType,
    LogisticsManager,
    TransferStatus,
    WeaponInventory,
)
from game.logistics import forward_cache
from game.logistics.crate_delivery import CrateReport, settle_transfer
from game.logistics.forward_cache import CacheCrate, cache_of, cache_tid
from game.theater.player import Player

TERRAIN = Caucasus()
HELLFIRE = str(Weapons.AGM_114K_Hellfire["clsid"])


class Cp:
    def __init__(self, name: str, x: float, owner: Player = Player.BLUE) -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.captured = owner
        self.is_fleet = False
        self.dcs_airport: Any = object()  # an airfield: 2.5 km radius
        self.position = Point(x, 0, TERRAIN)


class World:
    """Home at x=0, Forward at x=40 km; drop zone "Hawk" of Forward at x=20 km
    (outside both bases), drop zone "Pad" of Forward at x=41 km (inside it)."""

    def __init__(self, caches: bool = True) -> None:
        self.home = Cp("Home", 0)
        self.forward = Cp("Forward", 40_000)
        self.enemy = Cp("Enemy", 90_000, Player.RED)
        self.lm = LogisticsManager()
        for cp in (self.home, self.forward):
            inv = WeaponInventory(cp_id=cp.id, cp_name=cp.name)
            inv.add_item(HELLFIRE, "AGM-114K", "Air-to-Ground Missile", 100)
            self.lm.set_weapon_inventory(inv)
        self.hawk = self._dz("Hawk", 20_000, self.forward)
        self.pad = self._dz("Pad", 41_000, self.forward)
        cps = {cp.id: cp for cp in (self.home, self.forward, self.enemy)}

        def find(cp_id: Any) -> Cp:
            if cp_id not in cps:
                raise KeyError(cp_id)
            return cps[cp_id]

        self.game: Any = SimpleNamespace(
            settings=SimpleNamespace(drop_zone_caches=caches),
            logistics=self.lm,
            theater=SimpleNamespace(
                terrain=TERRAIN,
                controlpoints=list(cps.values()),
                find_control_point_by_id=find,
            ),
            blue=SimpleNamespace(
                faction=SimpleNamespace(country=SimpleNamespace(name="USA")),
                ato=SimpleNamespace(packages=[]),
            ),
        )

    def _dz(self, name: str, x: float, cp: Cp) -> DropZone:
        ll = Point(x, 0, TERRAIN).latlng()
        dz = DropZone(
            name=name,
            dz_type=DropZoneType.CARGO,
            lat=ll.lat,
            lon=ll.lng,
            cp_id=cp.id,
            coalition="blue",
            cp_name=cp.name,
        )
        self.lm.add_drop_zone(dz)
        return dz

    def stock(self, cp: Cp) -> int:
        inv = self.lm.get_weapon_inventory(cp.id)
        assert inv is not None
        return inv.items[HELLFIRE].quantity

    def transfer(self, count: int = 8) -> Any:
        t = self.lm.create_flight_transfer(
            self.home.id, self.forward.id, self.hawk.dz_id, "CH-47Fbl1", 1
        )
        t.cargo = {HELLFIRE: count}
        self.lm._take_weapons(self.home.id, t.cargo)  # loaded at planning
        t.status = TransferStatus.IN_FLIGHT
        return t


def crate(
    tid: str,
    x: float,
    count: int = 8,
    name: str = "Cargo 1/1",
    exists: bool = True,
    destroyed: bool = False,
    agl: float = 0.5,
    source: Optional[Cp] = None,
) -> CrateReport:
    return CrateReport(
        name=name,
        tid=tid,
        source=str(source.id) if source else "",
        contents={HELLFIRE: count},
        requested=False,
        destroyed=destroyed,
        exists=exists,
        x=x,
        z=0,
        agl=agl,
    )


# --- transfer crates ------------------------------------------------------------


def test_a_crate_set_down_in_a_drop_zone_stays_there() -> None:
    w = World()
    t = w.transfer()
    lines = settle_transfer(
        w.game, w.lm, t, [crate(t.transfer_id[:8], 20_100, source=w.home)], False
    )
    assert cache_of(w.lm, w.hawk.dz_id) == {HELLFIRE: 8}
    assert w.stock(w.forward) == 100, "not in the base's stores yet"
    assert w.stock(w.home) == 92
    assert t.status is TransferStatus.DELIVERED
    assert "delivered to the forward cache at Hawk" in lines[0]


def test_setting_off_delivers_to_the_base() -> None:
    w = World(caches=False)
    t = w.transfer()
    settle_transfer(
        w.game, w.lm, t, [crate(t.transfer_id[:8], 20_100, source=w.home)], False
    )
    assert cache_of(w.lm, w.hawk.dz_id) == {}
    assert w.stock(w.forward) == 108


def test_a_drop_zone_inside_the_base_delivers_to_the_base() -> None:
    w = World()
    t = w.transfer()
    settle_transfer(
        w.game, w.lm, t, [crate(t.transfer_id[:8], 41_000, source=w.home)], False
    )
    assert cache_of(w.lm, w.pad.dz_id) == {}
    assert w.stock(w.forward) == 108


def test_a_crate_still_under_the_helicopter_is_not_cached() -> None:
    w = World()
    t = w.transfer()
    settle_transfer(
        w.game,
        w.lm,
        t,
        [crate(t.transfer_id[:8], 20_100, agl=30, source=w.home)],
        False,
    )
    assert cache_of(w.lm, w.hawk.dz_id) == {}
    assert w.stock(w.home) == 100, "back to the pickup base"


# --- cache crates in later missions ---------------------------------------------


def _cached(w: World, *xs: float) -> list[str]:
    for x in xs:
        w.lm._drop_zone_caches.append(CacheCrate(w.hawk.dz_id, {HELLFIRE: 4}, x, 0))
    return list(forward_cache.placed_crates(w.game))


def _report(name: str, x: float, **kw: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "tid": cache_tid(_dz_id(name)),
        "contents": [{"clsid": HELLFIRE, "count": 4}],
        "exists": kw.get("exists", True),
        "destroyed": kw.get("destroyed", False),
        "x": x,
        "z": 0,
        "agl": kw.get("agl", 0.2),
    }


def _dz_id(name: str) -> str:
    return _DZ_IDS[name.split()[1]]


_DZ_IDS: Dict[str, str] = {}


@pytest.fixture
def world() -> World:
    w = World()
    _DZ_IDS[cache_tid(w.hawk.dz_id)] = w.hawk.dz_id
    _DZ_IDS[cache_tid(w.pad.dz_id)] = w.pad.dz_id
    return w


def test_cache_crates_are_named_per_drop_zone(world: World) -> None:
    names = _cached(world, 20_000, 20_010)
    tid = cache_tid(world.hawk.dz_id)
    assert tid.startswith("C") and len(tid) == 8
    assert [n.split(":")[0] for n in names] == [f"Cache {tid} 1/2", f"Cache {tid} 2/2"]


def test_carried_to_a_base_goes_into_its_stores(world: World) -> None:
    (name,) = _cached(world, 20_000)
    log = forward_cache.settle(world.game, [_report(name, 40_200)])
    assert world.stock(world.forward) == 104
    assert forward_cache.caches(world.lm) == []
    assert "delivered to Forward" in log[0]


def test_moved_in_the_field_stays_where_it_was_left(world: World) -> None:
    (name,) = _cached(world, 20_000)
    forward_cache.settle(world.game, [_report(name, 25_000)])
    (left,) = forward_cache.caches(world.lm)
    assert (left.x, left.dz_id) == (25_000, world.hawk.dz_id)


def test_moved_to_another_drop_zone_joins_its_cache(world: World) -> None:
    other = world._dz("Ridge", 30_000, world.forward)
    (name,) = _cached(world, 20_000)
    log = forward_cache.settle(world.game, [_report(name, 30_050)])
    assert cache_of(world.lm, other.dz_id) == {HELLFIRE: 4}
    assert "moved to Ridge" in log[0]


def test_destroyed_is_lost(world: World) -> None:
    (name,) = _cached(world, 20_000)
    forward_cache.settle(world.game, [_report(name, 0, exists=False, destroyed=True)])
    assert forward_cache.caches(world.lm) == []


@pytest.mark.parametrize("kw", [{"exists": False}, {"agl": 40.0}])
def test_in_an_aircraft_at_the_end_goes_back_where_it_was(
    world: World, kw: Any
) -> None:
    names = _cached(world, 20_000, 20_010)
    forward_cache.settle(world.game, [_report(names[0], 33_000, **kw)])
    assert sorted(c.x for c in forward_cache.caches(world.lm)) == [20_000, 20_010]


def test_no_report_leaves_the_caches_alone(world: World) -> None:
    _cached(world, 20_000)
    assert forward_cache.settle(world.game, []) == []
    assert len(forward_cache.caches(world.lm)) == 1


# --- removing a drop zone -----------------------------------------------------------


def test_removing_the_drop_zone_returns_the_cache_to_its_base(world: World) -> None:
    _cached(world, 20_000, 20_010)
    world.lm.remove_drop_zone(world.hawk.dz_id, world.game)
    assert forward_cache.caches(world.lm) == []
    assert world.stock(world.forward) == 108
    assert any("back to Forward" in line for line in world.lm.pop_debrief_log())


def test_a_lost_base_loses_the_cache(world: World) -> None:
    _cached(world, 20_000)
    world.forward.captured = Player.RED
    log = forward_cache.release(world.game, world.hawk)
    assert "lost" in log[0] and world.stock(world.forward) == 100


# --- the mission ----------------------------------------------------------------------


def test_cache_crates_are_placed_and_reported_by_the_cargo_script(world: World) -> None:
    from game.missiongenerator.transfercargogenerator import TransferCargoGenerator

    (name,) = _cached(world, 20_000)
    mission = Mission(TERRAIN)
    generator = TransferCargoGenerator(mission, world.game, SimpleNamespace(aircraft={}))  # type: ignore[arg-type]
    assert generator.generate() == 1
    statics = [
        g for c in mission.coalition["blue"].countries.values() for g in c.static_group
    ]
    (group,) = statics
    unit = group.units[0]
    assert str(unit.name) == name
    assert (unit.position.x, unit.position.y) == (20_000, 0)
    assert unit.can_cargo and (unit.mass or 0) > 0
    (script,) = generator.crates
    assert script["tid"] == cache_tid(world.hawk.dz_id)
    (trigger,) = [t for t in mission.triggerrules.triggers if "cargo" in str(t.comment)]
    assert "dcsRetributionCargo" in trigger.actions[0].dict()["text"]


def test_nothing_placed_with_the_setting_off(world: World) -> None:
    _cached(world, 20_000)
    world.game.settings.drop_zone_caches = False
    assert forward_cache.mission_crates(world.game) == []


def test_old_saves_start_without_caches() -> None:
    state = dict(LogisticsManager().__dict__)
    state.pop("_drop_zone_caches")
    restored = LogisticsManager.__new__(LogisticsManager)
    restored.__setstate__(state)
    assert restored._drop_zone_caches == []


def test_setting_is_on_by_default() -> None:
    from game.settings import Settings

    assert Settings().drop_zone_caches is True
