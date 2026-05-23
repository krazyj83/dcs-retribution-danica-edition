from __future__ import annotations

import itertools
import logging
from functools import cached_property
from pathlib import Path
from typing import Iterator, List, Optional, TYPE_CHECKING, Tuple
from uuid import UUID

from dcs import Mission
from dcs.countries import CombinedJointTaskForcesBlue, CombinedJointTaskForcesRed
from dcs.country import Country
from dcs.planes import F_15C, A_10A, AJS37, C_130
from dcs.ships import HandyWind, LHA_Tarawa, Stennis, USS_Arleigh_Burke_IIa
from dcs.statics import Fortification, Warehouse
from dcs.terrain import Airport
from dcs.unitgroup import PlaneGroup, ShipGroup, StaticGroup, VehicleGroup
from dcs.vehicles import AirDefence, Armor, MissilesSS, Unarmed

from game.controlpoint_influenceradius import ControlPointInfluenceRadius, point_in_zone
from game.point_with_heading import PointWithHeading
from game.positioned import Positioned
from game.profiling import logged_duration
from game.scenery_group import SceneryGroup
from game.theater.controlpoint import (
    Airfield,
    Carrier,
    ControlPoint,
    ControlPointType,
    Player,
    Fob,
    Lha,
    OffMapSpawn,
)
from game.theater.presetlocation import PresetLocation
from game.utils import Distance, meters, feet, Heading

if TYPE_CHECKING:
    from game.theater.conflicttheater import ConflictTheater
    from dcs import Point


class MizCampaignLoader:
    BLUE_COUNTRY = CombinedJointTaskForcesBlue()
    RED_COUNTRY = CombinedJointTaskForcesRed()

    OFF_MAP_UNIT_TYPE = F_15C.id
    GROUND_SPAWN_UNIT_TYPE = A_10A.id
    GROUND_SPAWN_ROADBASE_UNIT_TYPE = AJS37.id
    GROUND_SPAWN_LARGE_UNIT_TYPE = C_130.id

    CV_UNIT_TYPE = Stennis.id
    LHA_UNIT_TYPE = LHA_Tarawa.id
    FRONT_LINE_UNIT_TYPE = Armor.M_113.id
    SHIPPING_LANE_UNIT_TYPE = HandyWind.id
    CP_CONVOY_SPAWN_TYPE = Armor.M1043_HMMWV_Armament.id

    FOB_UNIT_TYPE = Unarmed.SKP_11.id
    FARP_HELIPADS_TYPE = ["Invisible FARP", "SINGLE_HELIPAD", "FARP"]
    INVISIBLE_FOB_UNIT_TYPE = Unarmed.M_818.id
    NEUTRAL_FOB_UNIT_TYPE = Unarmed.KrAZ6322.id

    OFFSHORE_STRIKE_TARGET_UNIT_TYPE = Fortification.Oil_platform.id
    SHIP_UNIT_TYPE = USS_Arleigh_Burke_IIa.id
    MISSILE_SITE_UNIT_TYPE = MissilesSS.Scud_B.id
    COASTAL_DEFENSE_UNIT_TYPE = MissilesSS.hy_launcher.id

    COMMAND_CENTER_UNIT_TYPE = Fortification._Command_Center.id
    CONNECTION_NODE_UNIT_TYPE = Fortification.Comms_tower_M.id
    POWER_SOURCE_UNIT_TYPE = Fortification.GeneratorF.id

    # Multiple options for air defenses so campaign designers can more accurately see
    # the coverage of their IADS for the expected type.
    LONG_RANGE_SAM_UNIT_TYPES = {
        AirDefence.Patriot_ln.id,
        AirDefence.S_300PS_5P85C_ln.id,
        AirDefence.S_300PS_5P85D_ln.id,
    }

    MEDIUM_RANGE_SAM_UNIT_TYPES = {
        AirDefence.Hawk_ln.id,
        AirDefence.S_75M_Volhov.id,
        AirDefence.x_5p73_s_125_ln.id,
        AirDefence.NASAMS_LN_B.id,
        AirDefence.NASAMS_LN_C.id,
    }

    SHORT_RANGE_SAM_UNIT_TYPES = {
        AirDefence.M1097_Avenger.id,
        AirDefence.rapier_fsa_launcher.id,
        AirDefence.x_2S6_Tunguska.id,
        AirDefence.Strela_1_9P31.id,
    }

    AAA_UNIT_TYPES = {
        AirDefence.flak18.id,
        AirDefence.Vulcan.id,
        AirDefence.ZSU_23_4_Shilka.id,
    }

    EWR_UNIT_TYPE = AirDefence.x_1L13_EWR.id

    ARMOR_GROUP_UNIT_TYPE = Armor.M_1_Abrams.id

    FACTORY_UNIT_TYPE = Fortification.Workshop_A.id

    AMMUNITION_DEPOT_UNIT_TYPE = Warehouse._Ammunition_depot.id

    STRIKE_TARGET_UNIT_TYPE = Fortification.Tech_combine.id

    # ── Name-prefix routing ────────────────────────────────────────────────────
    # Vehicle group names starting with these prefixes are routed to the matching
    # preset list regardless of what unit type is placed in the group.
    # This lets campaign designers use ANY unit as a placeholder — the actual
    # units spawned in the mission come from the faction's force groups.
    #
    # Prefix matching is case-insensitive and is checked BEFORE unit-type matching,
    # so a named prefix always wins. All existing campaigns remain fully compatible
    # because their placeholder unit types are still matched in the second pass.
    #
    # Example usage in the mission editor:
    #   Group name "SAM-LR-NorthKorea" with a T-72 inside → routes to long_range_sams
    #   Group name "ARMOR-Checkpoint1" with a BMP-2 inside → routes to armor_groups
    #   Group name "EWR-Valley" with any unit → routes to ewrs
    NAME_PREFIX_ROUTES: dict[str, str] = {
        "SAM-LR-":  "long_range_sams",
        "SAM-MR-":  "medium_range_sams",
        "SAM-SR-":  "short_range_sams",
        "AAA-":     "aaa",
        "EWR-":     "ewrs",
        "ARMOR-":   "armor_groups",
        "MISSILE-": "missile_sites",
        "COASTAL-": "coastal_defenses",
        "SHIP-":    "ships",
        "STRIKE-":  "strike_locations",
    }

    # Unit types used internally that must never be treated as custom ground objects.
    # Any vehicle group whose first unit matches one of these is silently skipped
    # during the custom_groups catch-all pass.
    _INTERNAL_UNIT_TYPES: frozenset[str] = frozenset()  # populated in __init_subclass__

    GROUND_SPAWN_WAYPOINT_DISTANCE = 1000

    def __init__(self, miz: Path, theater: ConflictTheater) -> None:
        self.theater = theater
        self.mission = Mission()
        with logged_duration("Loading miz"):
            self.mission.load_file(str(miz))

        # If there are no red carriers there usually aren't red units. Make sure
        # both countries are initialized so we don't have to deal with None.
        if self.mission.country(self.BLUE_COUNTRY.name) is None:
            self.mission.coalition["blue"].add_country(self.BLUE_COUNTRY)
        if self.mission.country(self.RED_COUNTRY.name) is None:
            self.mission.coalition["red"].add_country(self.RED_COUNTRY)

        # Build the set of internal unit type IDs that must never become custom
        # ground objects. We do this here so subclasses can override the class-level
        # constants before __init__ runs.
        self._skip_unit_types: frozenset[str] = frozenset({
            self.FRONT_LINE_UNIT_TYPE,
            self.CP_CONVOY_SPAWN_TYPE,
            self.FOB_UNIT_TYPE,
            self.INVISIBLE_FOB_UNIT_TYPE,
            self.NEUTRAL_FOB_UNIT_TYPE,
        })

    def control_point_from_airport(
        self, airport: Airport, ctld_zones: List[Tuple[Point, float]]
    ) -> ControlPoint:
        if airport.dynamic_spawn:
            starting_coalition = Player.NEUTRAL
        elif airport.is_blue():
            starting_coalition = Player.BLUE
        else:
            starting_coalition = Player.RED
        cp = Airfield(airport, self.theater, starting_coalition, ctld_zones=ctld_zones)

        # Use the unlimited aircraft option to determine if an airfield should
        # be owned by the player when the campaign is "inverted".
        cp.captured_invert = airport.unlimited_aircrafts

        return cp

    def country(self, blue: Player) -> Country:
        if blue.is_blue:
            country = self.mission.country(self.BLUE_COUNTRY.name)
        else:
            country = self.mission.country(self.RED_COUNTRY.name)
        # Should be guaranteed because we initialized them.
        assert country
        return country

    @property
    def blue(self) -> Country:
        return self.country(blue=Player.BLUE)

    @property
    def red(self) -> Country:
        return self.country(blue=Player.RED)

    def off_map_spawns(self, blue: Player) -> Iterator[PlaneGroup]:
        for group in self.country(blue).plane_group:
            if group.units[0].type == self.OFF_MAP_UNIT_TYPE:
                yield group

    def carriers(self, blue: Player) -> Iterator[ShipGroup]:
        for group in self.country(blue).ship_group:
            if group.units[0].type == self.CV_UNIT_TYPE:
                yield group

    def lhas(self, blue: Player) -> Iterator[ShipGroup]:
        for group in self.country(blue).ship_group:
            if group.units[0].type == self.LHA_UNIT_TYPE:
                yield group

    def fobs(self, blue: Player) -> Iterator[VehicleGroup]:
        for group in self.country(blue).vehicle_group:
            if group.units[0].type == self.FOB_UNIT_TYPE:
                yield group

    def invisible_fobs(self, blue: Player) -> Iterator[VehicleGroup]:
        for group in self.country(blue).vehicle_group:
            if group.units[0].type == self.INVISIBLE_FOB_UNIT_TYPE:
                yield group

    @property
    def neutral_fobs(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type == self.NEUTRAL_FOB_UNIT_TYPE:
                yield group

    @property
    def ships(self) -> Iterator[ShipGroup]:
        for group in self.red.ship_group:
            if group.units[0].type == self.SHIP_UNIT_TYPE:
                yield group

    @property
    def offshore_strike_targets(self) -> Iterator[StaticGroup]:
        for group in self.red.static_group:
            if group.units[0].type == self.OFFSHORE_STRIKE_TARGET_UNIT_TYPE:
                yield group

    @property
    def missile_sites(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type == self.MISSILE_SITE_UNIT_TYPE:
                yield group

    @property
    def coastal_defenses(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type == self.COASTAL_DEFENSE_UNIT_TYPE:
                yield group

    @property
    def long_range_sams(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type in self.LONG_RANGE_SAM_UNIT_TYPES:
                yield group

    @property
    def medium_range_sams(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type in self.MEDIUM_RANGE_SAM_UNIT_TYPES:
                yield group

    @property
    def short_range_sams(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type in self.SHORT_RANGE_SAM_UNIT_TYPES:
                yield group

    @property
    def aaa(self) -> Iterator[VehicleGroup]:
        for group in itertools.chain(self.blue.vehicle_group, self.red.vehicle_group):
            if group.units[0].type in self.AAA_UNIT_TYPES:
                yield group

    @property
    def ewrs(self) -> Iterator[VehicleGroup]:
        for group in self.red.vehicle_group:
            if group.units[0].type in self.EWR_UNIT_TYPE:
                yield group

    @property
    def armor_groups(self) -> Iterator[VehicleGroup]:
        for group in itertools.chain(self.blue.vehicle_group, self.red.vehicle_group):
            if group.units[0].type in self.ARMOR_GROUP_UNIT_TYPE:
                yield group

    @property
    def helipads(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.FARP_HELIPADS_TYPE:
                yield group

    @property
    def ground_spawns_roadbase(self) -> Iterator[PlaneGroup]:
        for group in itertools.chain(self.blue.plane_group, self.red.plane_group):
            if group.units[0].type == self.GROUND_SPAWN_ROADBASE_UNIT_TYPE:
                yield group

    @property
    def ground_spawns_large(self) -> Iterator[PlaneGroup]:
        for group in itertools.chain(self.blue.plane_group, self.red.plane_group):
            if group.units[0].type == self.GROUND_SPAWN_LARGE_UNIT_TYPE:
                yield group

    @property
    def ground_spawns(self) -> Iterator[PlaneGroup]:
        for group in itertools.chain(self.blue.plane_group, self.red.plane_group):
            if group.units[0].type == self.GROUND_SPAWN_UNIT_TYPE:
                yield group

    @property
    def factories(self) -> Iterator[StaticGroup]:
        for group in self.blue.static_group:
            if group.units[0].type in self.FACTORY_UNIT_TYPE:
                yield group

    @property
    def ammunition_depots(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.AMMUNITION_DEPOT_UNIT_TYPE:
                yield group

    @property
    def strike_targets(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.STRIKE_TARGET_UNIT_TYPE:
                yield group

    @property
    def scenery(self) -> List[SceneryGroup]:
        return SceneryGroup.from_trigger_zones(self.mission.triggers._zones)

    @cached_property
    def cp_influence_zones(self) -> List[ControlPointInfluenceRadius]:
        return ControlPointInfluenceRadius.from_trigger_zones(
            self.mission.triggers._zones
        )

    @cached_property
    def control_points(self) -> dict[UUID, ControlPoint]:
        control_points = {}
        for airport in self.mission.terrain.airport_list():
            if airport.is_blue() or airport.is_red() or airport.is_neutral():
                ctld_zones = self.get_ctld_zones(airport.name)
                control_point = self.control_point_from_airport(airport, ctld_zones)
                control_points[control_point.id] = control_point

        for blue in (Player.RED, Player.BLUE):
            for group in self.off_map_spawns(blue):
                control_point = OffMapSpawn(
                    str(group.name), group.position, self.theater, starts_blue=blue
                )
                control_point.captured_invert = group.late_activation
                control_points[control_point.id] = control_point
            for ship in self.carriers(blue):
                control_point = Carrier(
                    ship.name, ship.position, self.theater, starts_blue=blue
                )
                control_point.captured_invert = ship.late_activation
                control_points[control_point.id] = control_point
            for ship in self.lhas(blue):
                control_point = Lha(
                    ship.name, ship.position, self.theater, starts_blue=blue
                )
                control_point.captured_invert = ship.late_activation
                control_points[control_point.id] = control_point
            for fob in self.fobs(blue):
                ctld_zones = self.get_ctld_zones(fob.name)
                control_point = Fob(
                    str(fob.name),
                    fob.position,
                    self.theater,
                    starts_blue=blue,
                    ctld_zones=ctld_zones,
                )
                control_point.captured_invert = fob.late_activation
                control_points[control_point.id] = control_point

            for fob in self.invisible_fobs(blue):
                ctld_zones = self.get_ctld_zones(fob.name)
                control_point = Fob(
                    str(fob.name),
                    fob.position,
                    self.theater,
                    starts_blue=blue,
                    ctld_zones=ctld_zones,
                    is_invisible=True,
                )
                control_point.captured_invert = fob.late_activation
                control_points[control_point.id] = control_point

        for fob in self.neutral_fobs:
            ctld_zones = self.get_ctld_zones(fob.name)
            control_point = Fob(
                str(fob.name),
                fob.position,
                self.theater,
                starts_blue=Player.NEUTRAL,
                ctld_zones=ctld_zones,
            )
            control_point.captured_invert = fob.late_activation
            control_points[control_point.id] = control_point

        if self.cp_influence_zones:
            for cp in control_points.values():
                for influence_radius in self.cp_influence_zones:
                    if cp.full_name == influence_radius.cp_name:
                        cp.influence_radius = influence_radius
        return control_points

    @property
    def front_line_path_groups(self) -> Iterator[VehicleGroup]:
        for group in self.country(blue=Player.BLUE).vehicle_group:
            if group.units[0].type == self.FRONT_LINE_UNIT_TYPE:
                yield group

    @property
    def shipping_lane_groups(self) -> Iterator[ShipGroup]:
        for group in self.country(blue=Player.BLUE).ship_group:
            if group.units[0].type == self.SHIPPING_LANE_UNIT_TYPE:
                yield group

    @property
    def iads_command_centers(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.COMMAND_CENTER_UNIT_TYPE:
                yield group

    @property
    def iads_connection_nodes(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.CONNECTION_NODE_UNIT_TYPE:
                yield group

    @property
    def iads_power_sources(self) -> Iterator[StaticGroup]:
        for group in itertools.chain(self.blue.static_group, self.red.static_group):
            if group.units[0].type in self.POWER_SOURCE_UNIT_TYPE:
                yield group

    @property
    def cp_convoy_spawns(self) -> Iterator[VehicleGroup]:
        for group in self.country(blue=Player.BLUE).vehicle_group:
            if group.units[0].type == self.CP_CONVOY_SPAWN_TYPE:
                yield group

    def _construct_cp_spawnpoints(self, start: Point) -> Tuple[Point, ...]:
        closest = self._find_closest_cp_spawn(start)
        if closest:
            return self._interpolate_points(closest, start)
        return tuple()

    @staticmethod
    def _interpolate_points(closest: VehicleGroup, start: Point) -> Tuple[Point, ...]:
        points = [start]
        waypoints = points + [wpt.position for wpt in closest.points]
        last = waypoints[0]
        meters100ft = feet(100).meters
        residual = 0.0
        for wpt in waypoints[1:]:
            dist = wpt.distance_to_point(last)
            fraction = meters100ft / dist  # 100ft separation
            interpol_count = int((dist + residual) / meters100ft - 1)
            offset = (meters100ft - residual) / dist
            if offset <= 1:
                points.append(last.lerp(wpt, offset))
            if offset + fraction <= 1:
                for i in range(1, interpol_count + 1):
                    points.append(last.lerp(wpt, i * fraction + offset))
            residual = (residual + dist - meters100ft * interpol_count) % meters100ft
            last = wpt
        return tuple(points)

    def _find_closest_cp_spawn(self, start: Point) -> Optional[VehicleGroup]:
        closest: Optional[VehicleGroup] = None
        for spawn in self.cp_convoy_spawns:
            if closest is None:
                closest = spawn
                continue
            dist = start.distance_to_point(closest.position)
            if start.distance_to_point(spawn.position) < dist:
                closest = spawn
        return closest

    @staticmethod
    def _add_helipad(helipads: list[PointWithHeading], static: StaticGroup) -> None:
        helipads.append(
            PointWithHeading.from_point(
                static.position, Heading.from_degrees(static.units[0].heading)
            )
        )

    def _add_ground_spawn(
        self,
        ground_spawns: list[tuple[PointWithHeading, Point]],
        plane_group: PlaneGroup,
    ) -> None:
        if len(plane_group.points) >= 2:
            first_waypoint = plane_group.points[1].position
        else:
            first_waypoint = plane_group.position.point_from_heading(
                plane_group.units[0].heading,
                self.GROUND_SPAWN_WAYPOINT_DISTANCE,
            )

        ground_spawns.append(
            (
                PointWithHeading.from_point(
                    plane_group.position,
                    Heading.from_degrees(plane_group.units[0].heading),
                ),
                first_waypoint,
            )
        )

    def _route_by_name_prefix(self, group: VehicleGroup) -> Optional[str]:
        """Return the PresetLocations field name if the group name starts with a
        known prefix, otherwise return None.  Comparison is case-insensitive."""
        name_upper = str(group.name).upper()
        for prefix, list_name in self.NAME_PREFIX_ROUTES.items():
            if name_upper.startswith(prefix.upper()):
                return list_name
        return None

    def add_supply_routes(self) -> None:
        for group in self.front_line_path_groups:
            # The unit will have its first waypoint at the source CP and the final
            # waypoint at the destination CP. Each waypoint defines the path of the
            # supply convoy.
            waypoints = [p.position for p in group.points]
            origin = self.theater.closest_control_point(waypoints[0])
            if origin is None:
                raise RuntimeError(
                    f"No control point near the first waypoint of {group.name}"
                )
            destination = self.theater.closest_control_point(waypoints[-1])
            if destination is None:
                raise RuntimeError(
                    f"No control point near the final waypoint of {group.name}"
                )

            o_spawns = self._construct_cp_spawnpoints(waypoints[0])
            d_spawns = self._construct_cp_spawnpoints(waypoints[-1])

            self.control_points[origin.id].create_convoy_route(
                destination, waypoints, o_spawns
            )
            self.control_points[destination.id].create_convoy_route(
                origin, list(reversed(waypoints)), d_spawns
            )

    def add_shipping_lanes(self) -> None:
        for group in self.shipping_lane_groups:
            # The unit will have its first waypoint at the source CP and the final
            # waypoint at the destination CP. Each waypoint defines the path of the
            # cargo ship.
            waypoints = [p.position for p in group.points]
            origin = self.theater.closest_control_point(waypoints[0])
            if origin is None:
                raise RuntimeError(
                    f"No control point near the first waypoint of {group.name}"
                )
            destination = self.theater.closest_control_point(waypoints[-1])
            if destination is None:
                raise RuntimeError(
                    f"No control point near the final waypoint of {group.name}"
                )

            self.control_points[origin.id].create_shipping_lane(destination, waypoints)
            self.control_points[destination.id].create_shipping_lane(
                origin, list(reversed(waypoints))
            )

    def objective_info(
        self, near: Positioned, allow_naval: bool = False
    ) -> Tuple[ControlPoint, Distance]:
        zones_containing_point = [
            z
            for z in self.cp_influence_zones
            if point_in_zone(z.zone_def, near.position)
        ]

        # Ensure we only consider naval control points if allow_naval is True
        candidates = [
            self.theater.control_point_named(z.cp_name) for z in zones_containing_point
        ]
        if not allow_naval:
            candidates = [
                cp
                for cp in candidates
                if cp.cptype
                not in [
                    ControlPointType.AIRCRAFT_CARRIER_GROUP,
                    ControlPointType.LHA_GROUP,
                    ControlPointType.OFF_MAP,
                ]
            ]
        else:
            candidates = [
                cp for cp in candidates if cp.cptype != ControlPointType.OFF_MAP
            ]

        if candidates:
            closest = min(
                candidates, key=lambda cp: cp.position.distance_to_point(near.position)
            )
            distance = meters(closest.position.distance_to_point(near.position))
            return closest, distance

        # If no zones contain the point, find the closest control point without an
        # influence radius.
        if not allow_naval:
            fallback_candidates = [
                cp
                for cp in self.theater.controlpoints
                if cp.cptype
                not in [
                    ControlPointType.AIRCRAFT_CARRIER_GROUP,
                    ControlPointType.LHA_GROUP,
                    ControlPointType.OFF_MAP,
                ]
            ]
        else:
            fallback_candidates = [
                cp
                for cp in self.theater.controlpoints
                if cp.cptype != ControlPointType.OFF_MAP
            ]

        fallback_candidates = [
            cp for cp in fallback_candidates if not cp.influence_radius
        ]
        if not fallback_candidates:
            raise RuntimeError(
                f"All control points have an influence zone but no zones contain "
                f"{near} at {near.position}"
            )
        closest = min(
            fallback_candidates,
            key=lambda cp: cp.position.distance_to_point(near.position),
        )
        distance = meters(closest.position.distance_to_point(near.position))
        return closest, distance

    def add_preset_locations(self) -> None:
        # claimed_vehicle_ids tracks which VehicleGroup objects (by Python id()) have
        # already been routed to a typed preset list.  Any group not claimed by the
        # name-prefix pass or the unit-type pass ends up in custom_groups so it still
        # gets spawned and tracked when killed.
        claimed_vehicle_ids: set[int] = set()

        # ── Static / ship objectives (no unit-type ambiguity) ─────────────────
        for static in self.offshore_strike_targets:
            closest, _ = self.objective_info(static)
            closest.preset_locations.offshore_strike_locations.append(
                PresetLocation.from_group(static)
            )

        for ship in self.ships:
            closest, _ = self.objective_info(ship, allow_naval=True)
            closest.preset_locations.ships.append(PresetLocation.from_group(ship))

        # ── Pass 1: name-prefix routing ───────────────────────────────────────
        # Check every vehicle group from both coalitions.  If the group name starts
        # with a known prefix it is routed to the corresponding preset list regardless
        # of the unit type placed inside it.  This lets campaign designers freely
        # choose any placeholder unit.
        all_vehicle_groups: list[VehicleGroup] = list(
            itertools.chain(self.blue.vehicle_group, self.red.vehicle_group)
        )

        for group in all_vehicle_groups:
            list_name = self._route_by_name_prefix(group)
            if list_name is None:
                continue
            closest, _ = self.objective_info(group)
            preset_list = getattr(closest.preset_locations, list_name)
            preset_list.append(PresetLocation.from_group(group))
            claimed_vehicle_ids.add(id(group))
            logging.debug(
                f"Name-prefix routed '{group.name}' → {list_name} "
                f"at {closest.name}"
            )

        # ── Pass 2: unit-type matching (backward-compatible) ──────────────────
        # Groups already claimed by the name-prefix pass are skipped.
        def _claim(group: VehicleGroup, list_name: str) -> None:
            if id(group) in claimed_vehicle_ids:
                return
            closest, _ = self.objective_info(group)
            preset_list = getattr(closest.preset_locations, list_name)
            preset_list.append(PresetLocation.from_group(group))
            claimed_vehicle_ids.add(id(group))

        for group in self.red.vehicle_group:
            if group.units[0].type == self.MISSILE_SITE_UNIT_TYPE:
                _claim(group, "missile_sites")

        for group in self.red.vehicle_group:
            if group.units[0].type == self.COASTAL_DEFENSE_UNIT_TYPE:
                _claim(group, "coastal_defenses")

        for group in self.red.vehicle_group:
            if group.units[0].type in self.LONG_RANGE_SAM_UNIT_TYPES:
                _claim(group, "long_range_sams")

        for group in self.red.vehicle_group:
            if group.units[0].type in self.MEDIUM_RANGE_SAM_UNIT_TYPES:
                _claim(group, "medium_range_sams")

        for group in self.red.vehicle_group:
            if group.units[0].type in self.SHORT_RANGE_SAM_UNIT_TYPES:
                _claim(group, "short_range_sams")

        for group in itertools.chain(self.blue.vehicle_group, self.red.vehicle_group):
            if group.units[0].type in self.AAA_UNIT_TYPES:
                _claim(group, "aaa")

        for group in self.red.vehicle_group:
            if group.units[0].type == self.EWR_UNIT_TYPE:
                _claim(group, "ewrs")

        for group in itertools.chain(self.blue.vehicle_group, self.red.vehicle_group):
            if group.units[0].type == self.ARMOR_GROUP_UNIT_TYPE:
                _claim(group, "armor_groups")

        # ── Pass 3: custom_groups catch-all ───────────────────────────────────
        # Any vehicle group not yet claimed that is also not an internal placeholder
        # (supply-route M113, convoy HMMWV, FOB markers) is added to custom_groups.
        # start_generator.py will spawn these as BASE_DEFENSE ground objects so they
        # appear in the mission, are registered in the UnitMap, and are counted when
        # destroyed in the debrief.
        for group in all_vehicle_groups:
            if id(group) in claimed_vehicle_ids:
                continue
            if group.units[0].type in self._skip_unit_types:
                continue
            closest, _ = self.objective_info(group)
            closest.preset_locations.custom_groups.append(
                PresetLocation.from_group(group)
            )
            claimed_vehicle_ids.add(id(group))
            logging.info(
                f"Custom group '{group.name}' (unit: {group.units[0].type}) "
                f"added to custom_groups at {closest.name}"
            )

        # ── Helipads, ground spawns, statics (unchanged) ──────────────────────
        for static in self.helipads:
            closest, _ = self.objective_info(static)
            if static.units[0].type == "SINGLE_HELIPAD":
                self._add_helipad(closest.helipads, static)
            elif static.units[0].type == "FARP":
                self._add_helipad(closest.helipads_quad, static)
            else:
                self._add_helipad(closest.helipads_invisible, static)

        for plane_group in self.ground_spawns_roadbase:
            closest, _ = self.objective_info(plane_group)
            self._add_ground_spawn(closest.ground_spawns_roadbase, plane_group)

        for plane_group in self.ground_spawns_large:
            closest, _ = self.objective_info(plane_group)
            self._add_ground_spawn(closest.ground_spawns_large, plane_group)

        for plane_group in self.ground_spawns:
            closest, _ = self.objective_info(plane_group)
            self._add_ground_spawn(closest.ground_spawns, plane_group)

        for static in self.factories:
            closest, _ = self.objective_info(static)
            closest.preset_locations.factories.append(PresetLocation.from_group(static))

        for static in self.ammunition_depots:
            closest, _ = self.objective_info(static)
            closest.preset_locations.ammunition_depots.append(
                PresetLocation.from_group(static)
            )

        for static in self.strike_targets:
            closest, _ = self.objective_info(static)
            closest.preset_locations.strike_locations.append(
                PresetLocation.from_group(static)
            )

        for iads_command_center in self.iads_command_centers:
            closest, _ = self.objective_info(iads_command_center)
            closest.preset_locations.iads_command_center.append(
                PresetLocation.from_group(iads_command_center)
            )

        for iads_connection_node in self.iads_connection_nodes:
            closest, _ = self.objective_info(iads_connection_node)
            closest.preset_locations.iads_connection_node.append(
                PresetLocation.from_group(iads_connection_node)
            )

        for iads_power_source in self.iads_power_sources:
            closest, _ = self.objective_info(iads_power_source)
            closest.preset_locations.iads_power_source.append(
                PresetLocation.from_group(iads_power_source)
            )

        for scenery_group in self.scenery:
            closest, _ = self.objective_info(scenery_group)
            closest.preset_locations.scenery.append(scenery_group)

    def populate_theater(self) -> None:
        for control_point in self.control_points.values():
            self.theater.add_controlpoint(control_point)
        self.add_preset_locations()
        self.add_supply_routes()
        self.add_shipping_lanes()
        self.add_rebel_zones()

    def get_ctld_zones(self, prefix: str) -> List[Tuple[Point, float]]:
        zones = [t for t in self.mission.triggers.zones() if prefix + " CTLD" in t.name]
        for z in zones:
            self.mission.triggers.zones().remove(z)
        return [(z.position, z.radius) for z in zones]

    def add_rebel_zones(self) -> None:
        zones = [
            t for t in self.mission.triggers.zones() if t.name.startswith("Rebels")
        ]
        for z in zones:
            self.mission.triggers.zones().remove(z)
        self.theater.add_rebel_zones(zones)
