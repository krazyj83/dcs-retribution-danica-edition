"""Campaigns with ``use_placed_units: true`` spawn groups exactly as placed."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any

from dcs.mapping import Point
from dcs.terrain import Caucasus
from dcs.unit import Vehicle
from dcs.unitgroup import VehicleGroup
from dcs.vehicles import AirDefence, Armor

from game.data.groups import GroupTask
from game.theater.iadsnetwork.iadsrole import IadsRole
from game.theater.player import Player
from game.theater.presetlocation import PlacedUnit, PresetLocation
from game.theater.start_generator import (
    AirbaseGroundObjectGenerator,
    has_air_defence,
    placed_unit_dcs_type,
)
from game.theater.theatergroundobject import SamGroundObject, VehicleGroupGroundObject
from game.theater.theatergroup import IadsGroundGroup

TERRAIN = Caucasus()


def _buk_site() -> PresetLocation:
    location = PresetLocation("SA-11 north", Point(1000, 2000, TERRAIN))
    location.placed_units = (
        PlacedUnit(AirDefence.SA_11_Buk_SR_9S18M1.id, "sr", 1000, 2000, 90),
        PlacedUnit(AirDefence.SA_11_Buk_CC_9S470M1.id, "cc", 1030, 2000, 90),
        PlacedUnit(AirDefence.SA_11_Buk_LN_9A310M1.id, "ln1", 1100, 2050, 45),
        PlacedUnit(AirDefence.SA_11_Buk_LN_9A310M1.id, "ln2", 1100, 1950, 135),
    )
    return location


def _generator(use_placed: bool) -> Any:
    ids = itertools.count(1)
    cp = SimpleNamespace(
        name="Maykop",
        captured=Player.RED,
        connected_objectives=[],
        position=Point(0, 0, TERRAIN),
    )
    game = SimpleNamespace(
        next_unit_id=lambda: next(ids),
        next_group_id=lambda: next(ids),
        coalition_for=lambda player: SimpleNamespace(faction=SimpleNamespace(name="X")),
    )
    settings = SimpleNamespace(use_placed_units=use_placed)
    return AirbaseGroundObjectGenerator(game, settings, cp)  # type: ignore[arg-type]


def test_preset_keeps_the_placed_units() -> None:
    group = VehicleGroup(1, "Armor 1")
    for i, unit_type in enumerate([Armor.M_1_Abrams, Armor.M_2_Bradley]):
        unit = Vehicle(TERRAIN, i + 1, f"u{i}", unit_type.id)
        unit.position = Point(100 * i, 50, TERRAIN)
        unit.heading = 30.0 * i
        group.add_unit(unit)

    preset = PresetLocation.from_group(group)

    assert [u.type_id for u in preset.placed_units] == [
        Armor.M_1_Abrams.id,
        Armor.M_2_Bradley.id,
    ]
    assert (preset.placed_units[1].x, preset.placed_units[1].heading) == (100, 30.0)


def test_old_presets_have_no_placed_units() -> None:
    preset = PresetLocation("old", Point(0, 0, TERRAIN))
    assert preset.placed_units == ()


def test_only_types_retribution_knows_can_be_placed() -> None:
    assert placed_unit_dcs_type(AirDefence.SA_11_Buk_LN_9A310M1.id) is not None
    assert placed_unit_dcs_type("No such unit") is None


def test_sam_site_is_spawned_unit_for_unit() -> None:
    generator = _generator(use_placed=True)
    location = _buk_site()

    assert generator.generate_placed_group(location, GroupTask.MERAD)

    [tgo] = generator.control_point.connected_objectives
    assert isinstance(tgo, SamGroundObject)
    [group] = tgo.groups
    assert isinstance(group, IadsGroundGroup)
    assert group.iads_role is IadsRole.SAM
    placed = [(u.type_id, u.x, u.y, u.heading) for u in location.placed_units]
    spawned = [
        (u.type.id, u.position.x, u.position.y, u.position.heading.degrees)
        for u in group.units
    ]
    assert spawned == placed


def test_armor_group_is_a_vehicle_group() -> None:
    generator = _generator(use_placed=True)
    location = PresetLocation("Armor", Point(0, 0, TERRAIN))
    location.placed_units = (PlacedUnit(Armor.M_1_Abrams.id, "t", 5, 5, 0),)

    assert generator.generate_placed_group(location, GroupTask.BASE_DEFENSE)
    [tgo] = generator.control_point.connected_objectives
    assert isinstance(tgo, VehicleGroupGroundObject)


def test_falls_back_to_faction_units() -> None:
    # Campaign did not opt in.
    assert not _generator(use_placed=False).generate_placed_group(
        _buk_site(), GroupTask.MERAD
    )
    # A placed type Retribution has no data for.
    location = _buk_site()
    location.placed_units = location.placed_units + (
        PlacedUnit("No such unit", "x", 0, 0, 0),
    )
    generator = _generator(use_placed=True)
    assert not generator.generate_placed_group(location, GroupTask.MERAD)
    assert generator.control_point.connected_objectives == []


def test_air_defence_is_recognised_for_the_name_prefix_warning() -> None:
    assert has_air_defence(_buk_site().placed_units)
    assert not has_air_defence((PlacedUnit(Armor.M_1_Abrams.id, "t", 0, 0, 0),))
