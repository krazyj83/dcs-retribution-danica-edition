from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from dcs.mapping import Point
from dcs.unitgroup import StaticGroup, ShipGroup, VehicleGroup

from game.point_with_heading import PointWithHeading
from game.utils import Heading

GroupT = TypeVar("GroupT", StaticGroup, ShipGroup, VehicleGroup)


@dataclass(frozen=True)
class PlacedUnit:
    """One unit exactly as the campaign designer placed it in the miz."""

    type_id: str  # DCS type name, e.g. "SA-11 Buk LN 9A310M1"
    name: str
    x: float
    y: float
    heading: float  # degrees


class PresetLocation(PointWithHeading):
    """Store information about the Preset Location set by the campaign designer"""

    # This allows to store original name and force a specific type or template
    original_name: str  # Store the original name from the campaign miz

    #: The units of the placed group, used when the campaign spawns placed units
    #: as-is (campaign yaml ``use_placed_units: true``). Class-level default so
    #: locations pickled before this existed still load.
    placed_units: tuple[PlacedUnit, ...] = ()

    def __init__(
        self, name: str, position: Point, heading: Heading = Heading.from_degrees(0)
    ) -> None:
        super().__init__(position.x, position.y, heading, position._terrain)
        self.original_name = name

    @classmethod
    def from_group(cls, group: GroupT) -> PresetLocation:
        """Creates a PresetLocation from a placeholder group in the campaign miz"""
        preset = PresetLocation(
            group.name,
            group.position,
            Heading.from_degrees(group.units[0].heading),
        )
        preset.placed_units = tuple(
            PlacedUnit(
                str(unit.type),
                str(unit.name),
                unit.position.x,
                unit.position.y,
                float(unit.heading),
            )
            for unit in group.units
        )
        return preset
