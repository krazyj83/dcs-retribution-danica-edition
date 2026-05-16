"""
game/logistics/dropzone.py

Drop zone data model. A DropZone is a player-defined area on the map
where helicopter or transport aircraft missions will deliver troops or
cargo. Each DropZone is tied to a ControlPoint (the owning base) and
has a lat/lon centre, radius, type (troop or cargo), and optional name.

DropZones are saved in the campaign JSON and injected into the DCS
mission file as trigger zones via pydcs, so that Lua scripts (JTAC,
MOOSE troop manager, etc.) can reference them by name at runtime.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DropZoneType(str, Enum):
    """What kind of payload this zone accepts."""
    TROOP = "troop"    # infantry delivery (helicopter insertion / HALO)
    CARGO = "cargo"    # supply crates, vehicles, ammunition pallets


@dataclass
class DropZone:
    """
    A named, circular area on the map where logistics missions deliver.

    Attributes:
        dz_id:       Unique ID (UUID4 string). Stable across saves.
        name:        Human-readable label, e.g. "LZ ALPHA" or "DZ BRAVO".
        dz_type:     TROOP or CARGO.
        lat:         Latitude of zone centre (decimal degrees).
        lon:         Longitude of zone centre (decimal degrees).
        radius_m:    Zone radius in metres. Default 500 m.
        cp_id:       ID of the owning ControlPoint (home base / FARP).
        coalition:   "blue" or "red" — which side owns this zone.
        active:      Whether the zone appears in the next generated mission.
        notes:       Optional freetext, shown in the Qt panel.
    """

    name: str
    dz_type: DropZoneType
    lat: float
    lon: float
    cp_id: int
    coalition: str = "blue"
    radius_m: float = 500.0
    active: bool = True
    notes: str = ""
    dz_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # pydcs trigger zone name used inside the .miz file.
    # Lua scripts reference zones by this exact string.
    # Format: "RETRIBUTION_DZ_{TYPE}_{NAME_SLUG}"
    # ------------------------------------------------------------------
    @property
    def trigger_zone_name(self) -> str:
        slug = self.name.upper().replace(" ", "_")
        return f"RETRIBUTION_DZ_{self.dz_type.value.upper()}_{slug}"

    # ------------------------------------------------------------------
    # Serialisation helpers (campaign JSON)
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "dz_id":     self.dz_id,
            "name":      self.name,
            "dz_type":   self.dz_type.value,
            "lat":       self.lat,
            "lon":       self.lon,
            "radius_m":  self.radius_m,
            "cp_id":     self.cp_id,
            "coalition": self.coalition,
            "active":    self.active,
            "notes":     self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DropZone:
        return cls(
            dz_id=data["dz_id"],
            name=data["name"],
            dz_type=DropZoneType(data["dz_type"]),
            lat=data["lat"],
            lon=data["lon"],
            radius_m=data.get("radius_m", 500.0),
            cp_id=data["cp_id"],
            coalition=data.get("coalition", "blue"),
            active=data.get("active", True),
            notes=data.get("notes", ""),
        )

    def __repr__(self) -> str:
        return (
            f"<DropZone {self.name!r} type={self.dz_type.value} "
            f"lat={self.lat:.4f} lon={self.lon:.4f} active={self.active}>"
        )
