"""Convoy escort: cover a player-drawn convoy along its whole route.

The flight flies to the route start, then flies a race track along the road
between the route start and the route end, attacking enemy ground units near
it, for as long as the convoy is estimated to take (the upper drive-time
estimate plus a margin), then returns home.
Convoys leave at mission start, so plan the package "as soon as possible" to
be on station when the convoy sets off.

The target is the ConvoyRouteTarget made by the map's "Plan Escort Mission"
button (game/theater/convoyroute.py).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Type

from game.theater.convoyroute import ConvoyRouteTarget, drive_time
from game.utils import Distance, Speed, meters, nautical_miles
from .cas import Builder as CasBuilder, CasFlightPlan, CasLayout
from .invalidobjectivelocation import InvalidObjectiveLocation
from .waypointbuilder import WaypointBuilder
from ..flightwaypointtype import FlightWaypointType

#: Extra time on station on top of the upper drive-time estimate.
STATION_MARGIN = timedelta(minutes=10)
#: The ingress point sits this far before the route start, towards home.
INGRESS_DISTANCE = nautical_miles(8)


class ConvoyEscortFlightPlan(CasFlightPlan):
    @staticmethod
    def builder_type() -> Type[Builder]:
        return Builder

    @property
    def route_length(self) -> Distance:
        return meters(
            self.layout.patrol_start.position.distance_to_point(
                self.layout.patrol_end.position
            )
        )

    @property
    def patrol_duration(self) -> timedelta:
        _, slowest = drive_time(self.route_length)
        return max(
            slowest + STATION_MARGIN, self.flight.coalition.doctrine.cas_duration
        )

    @property
    def patrol_speed(self) -> Speed:
        return self.flight.unit_type.preferred_patrol_speed(
            self.layout.patrol_start.alt
        )

    @property
    def engagement_distance(self) -> Distance:
        # The engagement zone is centred on the middle of the road, so it has
        # to reach both ends of it.
        cas_range = super().engagement_distance
        half_route = meters(self.route_length.meters / 2) + nautical_miles(3)
        return max(cas_range, half_route, key=lambda d: d.meters)


class Builder(CasBuilder):
    """Same layout as CAS, along the convoy route instead of the front line."""

    def layout(self, dump_debug_info: bool) -> CasLayout:
        target = self.package.target
        if (
            not isinstance(target, ConvoyRouteTarget)
            or target.start is None
            or target.end is None
        ):
            raise InvalidObjectiveLocation(self.flight.flight_type, target)

        start, end = target.start, target.end
        builder = WaypointBuilder(self.flight)
        is_helo = self.flight.unit_type.dcs_unit_type.helicopter
        altitude = builder.get_combat_altitude

        home = self.flight.departure.position
        heading = start.heading_between_point(home)
        ingress_point = start.point_from_heading(heading, INGRESS_DISTANCE.meters)

        drive = drive_time(meters(start.distance_to_point(end)))
        start_wp = builder.cas(start, altitude)
        start_wp.name = "CONVOY START"
        start_wp.pretty_name = "Convoy start"
        start_wp.description = (
            f"{target.name}: the convoy leaves here at mission start "
            f"({_format(drive[0])}-{_format(drive[1])} to the end)"
        )
        end_wp = builder.cas(end, altitude)
        end_wp.name = "CONVOY END"
        end_wp.pretty_name = "Convoy end"
        end_wp.description = f"{target.name}: the convoy's destination"
        # Race track along the road (RaceTrackBuilder: engage, then orbit
        # between the two points until the patrol time is up).
        start_wp.waypoint_type = FlightWaypointType.PATROL_TRACK
        end_wp.waypoint_type = FlightWaypointType.PATROL

        ingress = builder.ingress(FlightWaypointType.INGRESS_CAS, ingress_point, target)
        ingress.description = f"Ingress to escort the convoy on {target.name}"

        return CasLayout(
            departure=builder.takeoff(self.flight.departure),
            nav_to=builder.nav_path(home, ingress_point, altitude, is_helo),
            nav_from=builder.nav_path(
                end, self.flight.arrival.position, altitude, is_helo
            ),
            ingress=ingress,
            patrol_start=start_wp,
            patrol_end=end_wp,
            arrival=builder.land(self.flight.arrival),
            divert=builder.divert(self.flight.divert),
            bullseye=builder.bullseye(),
            custom_waypoints=list(),
        )

    def build(self, dump_debug_info: bool = False) -> ConvoyEscortFlightPlan:
        return ConvoyEscortFlightPlan(self.flight, self.layout(dump_debug_info))


def _format(duration: timedelta) -> str:
    minutes = int(duration.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"
