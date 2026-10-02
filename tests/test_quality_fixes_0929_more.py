"""Batch 1 of the 29 Sep quality check, the fixes that had no test yet:

- B2: the fork's data tables load before the plugin scripts that read them.
- B10: Convoy Escort gets no extra unzoned engage task at the race track.
- B12: a skipped turn's debrief lines go to its turn report, not the next debrief.

B3 (ship weapons plugin option) is tested in test_ship_weapons_lua.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from dcs import Mission
from dcs.mapping import Point
from dcs.point import MovingPoint
from dcs.task import EngageTargets
from dcs.triggers import TriggerStart

from game.ato import FlightType
from game.ato.flightplans.patrolling import PatrollingFlightPlan
from game.logistics import LogisticsManager
from game.logistics.turn_report import TurnReport, file_skipped_turn, latest
from game.missiongenerator.aircraft.waypoints import racetrack
from game.missiongenerator.aircraft.waypoints.racetrack import RaceTrackBuilder
from game.missiongenerator.luadata import inject_data_table
from game.missiongenerator.luagenerator import LuaGenerator
from game.utils import knots, nautical_miles

# --- B2: data tables before the plugin scripts --------------------------------


def _comments(mission: Mission) -> list[str]:
    return [str(t.comment) for t in mission.triggerrules.triggers]


def test_data_tables_stay_ahead_of_the_plugin_scripts() -> None:
    mission = Mission()
    inject_data_table(mission, "dcsRetributionWarehouses", {"x": 1}, "warehouse")
    ewrj = TriggerStart(comment="EWRJ jammers")
    mission.triggerrules.triggers.append(ewrj)

    generator = LuaGenerator(None, mission, None)  # type: ignore[arg-type]

    def plugins() -> None:  # stands in for generate_plugin_data/inject_plugins
        mission.triggerrules.triggers.append(TriggerStart(comment="plugin scripts"))

    generator.generate_plugin_data = plugins  # type: ignore[method-assign]
    generator.inject_plugins = lambda: None  # type: ignore[method-assign]
    generator.generate()

    assert _comments(mission) == [
        "Set DCS Retribution warehouse data",
        "plugin scripts",
        "EWRJ jammers",  # moved behind the scripts, as before
    ]


# --- B10: no extra engage task for Convoy Escort -------------------------------


class _Patrol(PatrollingFlightPlan[Any]):
    """Just the patrol numbers RaceTrackBuilder reads."""

    patrol_speed = knots(300)
    engagement_distance = nautical_miles(10)
    patrol_start_time = datetime(2026, 1, 1, 12)
    patrol_end_time = datetime(2026, 1, 1, 13)
    patrol_duration = timedelta(hours=1)


def _engage_tasks(flight_type: FlightType, monkeypatch: Any) -> int:
    monkeypatch.setattr(racetrack, "create_stop_orbit_trigger", lambda *a: None)
    settings = SimpleNamespace(
        ai_unlimited_fuel=False,
        plugins={},
        plugin_option=lambda name: False,
    )
    game = SimpleNamespace(settings=settings)
    builder = object.__new__(RaceTrackBuilder)
    builder.flight = SimpleNamespace(  # type: ignore[assignment]
        flight_type=flight_type,
        flight_plan=object.__new__(_Patrol),
        squadron=SimpleNamespace(coalition=SimpleNamespace(game=game)),
        coalition=SimpleNamespace(game=game),
    )
    builder.now = datetime(2026, 1, 1, 12)
    builder.package = None  # type: ignore[assignment]
    builder.mission = None  # type: ignore[assignment]
    builder.set_waypoint_tot = lambda *a: None  # type: ignore[method-assign]

    waypoint = MovingPoint(Point(0, 0, None))  # type: ignore[arg-type]
    builder.add_tasks(waypoint)
    return sum(isinstance(t, EngageTargets) for t in waypoint.tasks)


def test_convoy_escort_gets_no_race_track_engage(monkeypatch: Any) -> None:
    assert _engage_tasks(FlightType.CONVOY_ESCORT, monkeypatch) == 0


def test_barcap_still_engages_at_the_race_track(monkeypatch: Any) -> None:
    # Proves the test above can see an engage task when there is one.
    assert _engage_tasks(FlightType.BARCAP, monkeypatch) == 1


# --- B12: skipped turn -----------------------------------------------------------


@pytest.fixture
def logistics() -> LogisticsManager:
    lm = LogisticsManager()
    lm._turn_reports[4] = TurnReport(turn=4, date="")
    return lm


def test_skipped_turn_lines_go_to_its_turn_report(logistics: Any) -> None:
    logistics.add_debrief_log(["Convoy arrived at Kutaisi", "Senaki captured"])

    file_skipped_turn(logistics)

    assert logistics.pop_debrief_log() == []  # nothing left for the next debrief
    report = latest(logistics)
    assert report is not None
    assert report.sections["events"] == [
        "Convoy arrived at Kutaisi",
        "Senaki captured",
    ]


def test_lines_already_in_the_report_are_not_repeated(logistics: Any) -> None:
    latest(logistics).add("events", ["Senaki captured"])  # type: ignore[union-attr]
    logistics.add_debrief_log(["Senaki captured"])

    file_skipped_turn(logistics)

    assert latest(logistics).sections["events"] == [  # type: ignore[union-attr]
        "Senaki captured"
    ]
