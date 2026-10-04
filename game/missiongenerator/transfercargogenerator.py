"""Place a weapon transfer's cargo next to the aircraft that will fly it.

For every BLUEFOR LOGISTIC flight carrying a weapon transfer, the cargo is
spawned as loadable DCS cargo objects (canCargo, mass set to the manifest
weight) so the player can pick it up straight away:

- The flight starts at the pickup base: the crates sit beside the aircraft
  (to the right of a helicopter, behind the ramp of a plane), within the
  45 m that DCS's ground crew lists for internal loading.
- The flight starts elsewhere: the crates wait at the pickup base, on a free
  parking spot (airfield) or next to the base (FARP/FOB).
- Ships and air starts at a pickup elsewhere get nothing (no safe spot); the
  transfer still settles as before.

Sling-load aircraft get one crate with the whole load; internal loaders
(CH-47F, C-130J) get crates of up to 1000 kg per weapon type.
Crate names read "Cargo <transfer id> <n>/<total>: <contents>".

It also writes the data table (``dcsRetributionCargo``) for the mission script
resources/plugins/base/retribution_cargo.lua, which gives client LOGISTIC
flights an F10 "Cargo" menu to order more crates from a base's stock, and
reports where every crate ended up (see game/logistics/crate_delivery.py).

Crates left in drop zones earlier (forward caches, game/logistics/
forward_cache.py) are placed again where they lay, and reported the same way.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional, Tuple

from dcs.mapping import Point
from dcs.statics import Cargo

from game.ato.flighttype import FlightType
from game.ato.starttype import StartType
from game.missiongenerator.luadata import inject_data_table
from game.logistics.cargo import (
    cargo_aircraft,
    loads_internally,
    pack_crates,
    weapon_weight_kg,
)

if TYPE_CHECKING:
    from dcs import Mission

    from game import Game
    from game.ato.flight import Flight
    from game.logistics import LogisticsTransfer
    from game.theater import ControlPoint
    from game.missiongenerator.missiondata import MissionData
    from game.unitmap import UnitMap

logger = logging.getLogger(__name__)

CRATE_TYPE = Cargo.ammo_cargo
#: Crates beside a helicopter: clear of the rotor disc, well inside 45 m.
HELI_SIDE_OFFSET_M = 25.0
#: Crates behind a plane's ramp.
PLANE_BEHIND_OFFSET_M = 35.0
#: Crates beside a base with no parking data (FARP / FOB).
BASE_OFFSET_M = 40.0
#: Gap between crates in a row.
CRATE_SPACING_M = 5.0


class TransferCargoGenerator:
    def __init__(
        self,
        mission: Mission,
        game: Game,
        unit_map: UnitMap,
        mission_data: Optional[MissionData] = None,
    ) -> None:
        self.mission = mission
        self.game = game
        self.unit_map = unit_map
        self.mission_data = mission_data
        #: Crates placed, for the mission script: name, transfer, contents.
        self.crates: list[dict[str, Any]] = []
        #: Client LOGISTIC flights that get the F10 Cargo menu, by group name.
        self.flights: dict[str, dict[str, Any]] = {}

    def generate(self) -> int:
        """Place crates for every weapon transfer flight. Returns crates placed."""
        logistics = getattr(self.game, "logistics", None)
        if logistics is None:
            return 0
        placed = 0
        for package in self.game.blue.ato.packages:
            for flight in package.flights:
                if flight.flight_type is not FlightType.LOGISTIC:
                    continue
                transfer = logistics._transfers.get(
                    getattr(flight, "transfer_id", None) or ""
                )
                if transfer is None or transfer.cargo is None:
                    continue
                self._register_flight(flight, transfer)
                if not transfer.cargo:
                    continue
                try:
                    placed += self._place(flight, transfer)
                except Exception:
                    logger.exception(
                        "Transfer %s: could not place its cargo",
                        transfer.transfer_id[:8],
                    )
        try:
            placed += self._place_caches()
        except Exception:
            logger.exception("Could not place the forward caches")
        if self.flights or self.crates:
            try:
                self._write_script_data()
            except Exception:
                logger.exception("Could not write the cargo menu data")
        return placed

    # ── Mission script data ───────────────────────────────────────────

    def _register_flight(self, flight: Flight, transfer: LogisticsTransfer) -> None:
        """Client flights get the F10 Cargo menu."""
        if not flight.client_count:
            return
        group = self._group_of(flight)
        if group is None:
            return
        weights = cargo_aircraft(flight.unit_type)
        entry: dict[str, Any] = {
            "tid": transfer.transfer_id[:8],
            "helicopter": bool(flight.unit_type.dcs_unit_type.helicopter),
        }
        if weights is not None:
            entry.update(
                emptyKg=weights.empty_kg,
                maxKg=weights.max_kg,
                fuelMaxKg=weights.fuel_max_kg,
            )
        self.flights[group.name] = entry

    def _write_script_data(self) -> None:
        from game.logistics import build_weapon_inventory
        from game.logistics.crate_delivery import base_radius_m, friendly_bases

        logistics = self.game.logistics
        bases: list[dict[str, Any]] = []
        stock: dict[str, list[dict[str, Any]]] = {}
        for cp in friendly_bases(self.game):
            bases.append(
                {
                    "id": str(cp.id),
                    "name": cp.name,
                    "x": cp.position.x,
                    "z": cp.position.y,
                    "radius": base_radius_m(cp),
                }
            )
            inv = logistics.get_weapon_inventory(cp.id)
            if inv is None:
                inv = build_weapon_inventory(cp, self.game)
                logistics.set_weapon_inventory(inv)
            items = []
            for item in sorted(inv.items.values(), key=lambda i: (i.category, i.name)):
                weight = weapon_weight_kg(item.clsid)
                if weight is not None and item.quantity > 0:
                    items.append(
                        {
                            "clsid": item.clsid,
                            "name": item.name,
                            "category": item.category,
                            "kg": weight,
                            "qty": item.quantity,
                        }
                    )
            stock[str(cp.id)] = items
        data = {
            "flights": self.flights,
            "bases": bases,
            "stock": stock,
            "crates": self.crates,
        }
        inject_data_table(self.mission, "dcsRetributionCargo", data, "cargo")

    # ── Placement ─────────────────────────────────────────────────────

    def _place_caches(self) -> int:
        """Crates left in drop zones, where they lay."""
        from game.logistics.forward_cache import mission_crates

        crates = mission_crates(self.game)
        if not crates:
            return 0
        country = self.mission.country(self.game.blue.faction.country.name)
        for crate in crates:
            group = self.mission.static_group(
                country,
                crate["name"],
                CRATE_TYPE,
                Point(crate["x"], crate["z"], self.mission.terrain),
                heading=0,
            )
            unit = group.units[0]
            unit.name = crate["name"]
            unit.mass = max(1, int(round(crate["mass"])))
            unit.can_cargo = True
            self.crates.append(crate["script"])
        logger.info("Forward caches: %d crate(s) placed", len(crates))
        return len(crates)

    def _place(self, flight: Flight, transfer: LogisticsTransfer) -> int:
        from game.logistics.transfer_flights import control_point

        assert transfer.cargo is not None
        source = control_point(self.game, transfer.source_cp_id)
        if source is None:
            return 0
        anchor = self._anchor(flight, source)
        if anchor is None:
            logger.info(
                "Transfer %s: no safe spot for cargo at %s; not placed",
                transfer.transfer_id[:8],
                source.name,
            )
            return 0
        start, row_heading, facing, where = anchor
        sheets = [
            data
            for data in (self.mission_data.flights if self.mission_data else [])
            if data.transfer_id == transfer.transfer_id
        ]

        crates = pack_crates(transfer.cargo, loads_internally(flight.unit_type))
        country = self.mission.country(flight.squadron.coalition.faction.country.name)
        tid = transfer.transfer_id[:8]
        for i, crate in enumerate(crates):
            position = start.point_from_heading(row_heading, i * CRATE_SPACING_M)
            group = self.mission.static_group(
                country,
                f"Cargo {tid} {i + 1}/{len(crates)}: {crate.label}",
                CRATE_TYPE,
                position,
                heading=facing,
            )
            unit = group.units[0]
            unit.mass = int(round(crate.mass_kg))
            unit.can_cargo = True
            self.crates.append(
                {
                    "name": unit.name,
                    "tid": tid,
                    "source": str(source.id),
                    "contents": [
                        {"clsid": c, "count": n} for c, n in crate.contents.items()
                    ],
                }
            )
            for data in sheets:  # for the kneeboard load sheet
                data.cargo_crates.append((crate.label, crate.mass_kg, position, where))
        logger.info(
            "Transfer %s: %d crate(s) placed at %s for %s",
            tid,
            len(crates),
            source.name,
            flight.unit_type,
        )
        return len(crates)

    def _anchor(
        self, flight: Flight, source: ControlPoint
    ) -> Optional[Tuple[Point, float, float, str]]:
        """(first crate position, row heading, crate facing, where it is)."""
        helicopter = bool(flight.unit_type.dcs_unit_type.helicopter)
        if source.is_fleet:
            return None  # no safe spot on a deck
        if source is flight.departure and flight.start_type is not StartType.IN_FLIGHT:
            unit = self._lead_unit(flight)
            if unit is not None:
                heading = float(unit.heading)
                if helicopter:
                    start = unit.position.point_from_heading(
                        heading + 90, HELI_SIDE_OFFSET_M
                    )
                    return start, heading, heading, "beside the aircraft (right)"
                start = unit.position.point_from_heading(
                    heading + 180, PLANE_BEHIND_OFFSET_M
                )
                return start, heading + 90, heading, "behind the aircraft"
        spot = self._free_parking_spot(source, helicopter)
        if spot is not None:
            return spot, 0.0, 0.0, f"parking area at {source.name}"
        return (
            source.position.point_from_heading(90, BASE_OFFSET_M),
            0.0,
            0.0,
            f"next to {source.name}",
        )

    def _lead_unit(self, flight: Flight) -> Any:
        """The flight's first DCS unit, found through the unit map."""
        group = self._group_of(flight)
        return group.units[0] if group is not None and group.units else None

    def _group_of(self, flight: Flight) -> Any:
        """The flight's DCS group, found through the unit map."""
        names = {
            name
            for name, unit in self.unit_map.aircraft.items()
            if unit.flight is flight
        }
        for group in self._aircraft_groups():
            if any(unit.name in names for unit in group.units):
                return group
        return None

    def _aircraft_groups(self) -> Iterator[Any]:
        for coalition in self.mission.coalition.values():
            for country in coalition.countries.values():
                yield from country.helicopter_group
                yield from country.plane_group

    @staticmethod
    def _free_parking_spot(source: ControlPoint, helicopter: bool) -> Optional[Point]:
        airport = source.dcs_airport
        if airport is None:
            return None
        free = [
            slot
            for slot in airport.parking_slots
            if slot.unit_id is None
            and (slot.helicopter if helicopter else slot.airplanes)
        ]
        # The last free slots are usually the least used.
        return free[-1].position if free else None
