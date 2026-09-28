"""Convoy Escort flights along a player-drawn convoy route."""

from __future__ import annotations

from datetime import timedelta

from game.ato.flightplans.flightplanbuildertypes import FlightPlanBuilderTypes
from game.ato.flightplans.convoyescort import ConvoyEscortFlightPlan
from game.ato.flighttype import FlightType
from game.ato.loadouts import Loadout
from game.dcs.aircrafttype import AircraftType
from game.theater.convoyroute import ConvoyRouteTarget, drive_time
from game.theater.player import Player
from game.utils import meters


def test_drive_time_matches_the_map_estimate() -> None:
    fastest, slowest = drive_time(meters(40000))
    # 40 km straight: 48-60 km of road at 40 km/h.
    assert fastest == timedelta(hours=1.2)
    assert slowest == timedelta(hours=1.5)


def test_convoy_escort_has_a_flight_plan() -> None:
    from types import SimpleNamespace
    from typing import Any

    flight: Any = SimpleNamespace(flight_type=FlightType.CONVOY_ESCORT)
    builder = FlightPlanBuilderTypes.for_flight(flight)
    assert builder is ConvoyEscortFlightPlan.builder_type()


def test_route_offers_convoy_escort_and_barcap() -> None:
    from dcs.mapping import Point
    from dcs.terrain import Caucasus

    point = Point(0, 0, Caucasus())
    target = ConvoyRouteTarget(name="MSR", position=point, start=point, end=point)
    assert list(target.mission_types(Player.BLUE)) == [
        FlightType.CONVOY_ESCORT,
        FlightType.BARCAP,
    ]


def test_cas_aircraft_can_escort_convoys_with_cas_loadouts() -> None:
    from types import SimpleNamespace
    from typing import Any

    a10: Any = SimpleNamespace(
        task_priorities={FlightType.CAS: 700}, carrier_capable=False
    )
    AircraftType.__post_init__(a10)
    assert a10.task_priorities[FlightType.CONVOY_ESCORT] == 700

    names = list(Loadout.default_loadout_names_for(FlightType.CONVOY_ESCORT))
    assert set(Loadout.default_loadout_names_for(FlightType.CAS)) <= set(names)
