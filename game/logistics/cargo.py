"""Weight-based cargo for BLUEFOR warehouse transfers.

A transfer carries specific weapons (e.g. 20 x AGM-114K). Each weapon's mass
comes from DCS's own weapon data, so every weapon in the game has a weight.

What an aircraft can lift depends on the fuel the player takes:

    cargo = max take-off weight - empty weight - (fuel % x fuel capacity)

Empty and max weights are in resources/logistics/cargo_aircraft.yaml (DCS
values, editable); fuel capacity is read from DCS. Aircraft missing from that
file can still fly transfers, but their load is not checked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

import yaml
from dcs.weapons_data import weapon_ids as _weapon_ids

if TYPE_CHECKING:
    from game.dcs.aircrafttype import AircraftType
    from game.theater import ControlPoint

KG_TO_LB = 2.20462
#: Fuel loads the player can pick, as a fraction of full tanks.
FUEL_FRACTIONS = (1.0, 0.5, 0.25)
#: Planning speed as a share of the aircraft's DCS maximum speed.
CRUISE_SHARE_OF_MAX_SPEED = 0.8

#: DCS weapon data by clsid (name, weight in kg, ...).
weapon_ids: dict[str, dict[str, Any]] = _weapon_ids  # type: ignore[assignment]

DATA_FILE = Path("resources/logistics/cargo_aircraft.yaml")


def lb(kg: float) -> float:
    return kg * KG_TO_LB


@dataclass(frozen=True)
class CargoAircraft:
    """Weights of one aircraft type, in kg."""

    empty_kg: float
    max_kg: float
    fuel_max_kg: float

    def weight_at_fuel_kg(self, fuel_fraction: float) -> float:
        return self.empty_kg + fuel_fraction * self.fuel_max_kg

    def payload_kg(self, fuel_fraction: float) -> float:
        return max(0.0, self.max_kg - self.weight_at_fuel_kg(fuel_fraction))


@lru_cache(maxsize=1)
def _aircraft_table() -> dict[str, dict[str, Any]]:
    try:
        with DATA_FILE.open(encoding="utf-8") as data:
            table = yaml.safe_load(data) or {}
    except OSError:
        logging.warning("No cargo weight data: %s is missing", DATA_FILE)
        return {}
    return {str(key): value for key, value in table.items()}


def cargo_aircraft(aircraft: AircraftType) -> Optional[CargoAircraft]:
    """Weights for an aircraft type, or None if it isn't in the data file."""
    unit_type = aircraft.dcs_unit_type
    data = _aircraft_table().get(unit_type.id)
    if data is None:
        return None
    return CargoAircraft(
        empty_kg=float(data["empty_kg"]),
        max_kg=float(data["max_kg"]),
        fuel_max_kg=float(unit_type.fuel_max),
    )


def weapon_weight_kg(clsid: str) -> Optional[float]:
    """DCS mass of one weapon/store, or None if DCS doesn't know the clsid."""
    data = weapon_ids.get(clsid)
    if data is None or data.get("weight") is None:
        return None
    return float(data["weight"])


def weapon_name(clsid: str) -> str:
    data = weapon_ids.get(clsid)
    return str(data["name"]) if data else clsid


def manifest_weight_kg(cargo: Mapping[str, int]) -> float:
    return sum((weapon_weight_kg(c) or 0.0) * n for c, n in cargo.items())


def manifest_summary(cargo: Mapping[str, int]) -> str:
    """'20x AGM-114K Hellfire, 38x M151 APKWS' for logs and tables."""
    return ", ".join(f"{n}x {weapon_name(c)}" for c, n in cargo.items() if n > 0)


#: Aircraft that load cargo internally (DCS dynamic cargo, ground crew menu).
#: Everything else carries it on the sling hook.
INTERNAL_CARGO_TYPES = {"CH-47Fbl1", "C-130J-30", "Hercules"}
#: Heaviest single crate for internal loading; bigger loads become more crates.
CRATE_MAX_KG = 1000.0


@dataclass(frozen=True)
class Crate:
    """One cargo object placed in the mission for a transfer."""

    contents: Dict[str, int]
    mass_kg: float

    @property
    def label(self) -> str:
        return manifest_summary(self.contents)


def loads_internally(aircraft: AircraftType) -> bool:
    return aircraft.dcs_unit_type.id in INTERNAL_CARGO_TYPES


def pack_crates(cargo: Mapping[str, int], internal: bool) -> List[Crate]:
    """Split a manifest into the cargo objects placed next to the aircraft.

    Sling-load aircraft lift one load at a time, so they get a single crate
    with everything (its mass already fits the aircraft: the load was checked
    at scheduling). Internal loaders get one or more crates per weapon type,
    each no heavier than CRATE_MAX_KG (always at least one weapon per crate).
    """
    cargo = {clsid: n for clsid, n in cargo.items() if n > 0}
    if not cargo:
        return []
    if not internal:
        return [Crate(dict(cargo), manifest_weight_kg(cargo))]
    crates: List[Crate] = []
    for clsid, count in cargo.items():
        each = weapon_weight_kg(clsid) or 0.0
        per_crate = max(1, int(CRATE_MAX_KG // each)) if each > 0 else count
        while count > 0:
            n = min(per_crate, count)
            crates.append(Crate({clsid: n}, each * n))
            count -= n
    return crates


@dataclass(frozen=True)
class RouteLegs:
    """Distances in metres for home -> pickup -> drop-off -> home."""

    to_pickup: float
    pickup_to_drop: float
    drop_to_home: float

    @property
    def total(self) -> float:
        return self.to_pickup + self.pickup_to_drop + self.drop_to_home


def route_legs(
    home: ControlPoint, source: ControlPoint, destination: ControlPoint
) -> RouteLegs:
    return RouteLegs(
        to_pickup=home.position.distance_to_point(source.position),
        pickup_to_drop=source.position.distance_to_point(destination.position),
        drop_to_home=destination.position.distance_to_point(home.position),
    )


def cruise_speed_kph(aircraft: AircraftType) -> float:
    return float(aircraft.dcs_unit_type.max_speed) * CRUISE_SHARE_OF_MAX_SPEED


def flight_time_minutes(distance_m: float, aircraft: AircraftType) -> float:
    speed = cruise_speed_kph(aircraft)
    if speed <= 0:
        return 0.0
    return distance_m / 1000 / speed * 60
