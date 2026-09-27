"""DTC cartridges built from real ``FlightWaypoint`` objects.

``test_dtc.py`` (kept identical to upstream PR #966) builds its waypoints as
``SimpleNamespace`` fakes that carry a ``display_name``. The real
``FlightWaypoint`` in this fork had no such attribute, so every cartridge raised
``AttributeError`` in the mission generator, which swallows it
("DTC: cartridge generation failed; mission unaffected"). These tests run the
same fixture through real waypoints so that cannot happen silently again.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from game.ato.flightwaypoint import FlightWaypoint
from game.ato.flightwaypointtype import FlightWaypointType
from game.missiongenerator.dtc.hornet import build_hornet_cartridge
from game.missiongenerator.dtc.viper import build_viper_cartridge
from game.utils import meters
from tests.missiongenerator.test_dtc import _hornet_fixture


def _real(fake: Any, pretty_name: str) -> FlightWaypoint:
    return FlightWaypoint(
        name=fake.name,
        waypoint_type=fake.waypoint_type,
        position=fake.position,
        alt=meters(fake.alt.meters),
        alt_type=fake.alt_type,
        targets=fake.targets,
        pretty_name=pretty_name,
        flyover=fake.flyover,
        tot=fake.tot,
        departure_time=fake.departure_time,
    )


def _fixture_with_real_waypoints(pretty_names: list[str]) -> tuple[Any, Any, Any]:
    flight, mission_data, game = _hornet_fixture()
    flight.waypoints = [
        _real(fake, pretty) for fake, pretty in zip(flight.waypoints, pretty_names)
    ]
    return flight, mission_data, game


def test_display_name_is_the_pretty_name() -> None:
    waypoint = FlightWaypoint(
        "TARGET",
        FlightWaypointType.TARGET_POINT,
        SimpleNamespace(x=0, y=0),  # type: ignore[arg-type]
        pretty_name="Target: SA-6 site",
    )
    assert waypoint.display_name == "Target: SA-6 site"


def test_hornet_cartridge_from_real_waypoints() -> None:
    flight, mission_data, game = _fixture_with_real_waypoints(
        ["Takeoff", "Tgt", "Recovery"]
    )

    cartridge = build_hornet_cartridge(flight, mission_data, game, "Test FA-18C")

    nav_pts = json.loads(cartridge.to_json())["data"]["WYPT"]["NAV_PTS"]
    assert [w["text_note"] for w in nav_pts] == ["Tgt", "Recovery"]


def test_viper_cartridge_from_real_waypoints() -> None:
    flight, mission_data, game = _fixture_with_real_waypoints(
        ["Takeoff", "Tgt", "Recovery"]
    )
    flight.aircraft_type = SimpleNamespace(dcs_unit_type=SimpleNamespace(id="F-16C_50"))

    cartridge = build_viper_cartridge(flight, mission_data, game, "Test F-16C")

    nav_pts = json.loads(cartridge.to_json())["data"]["MPD"]["NAV_PTS"]
    assert [p["note"] for p in nav_pts[:2]] == ["Tgt", "Recovery"]


def test_blank_pretty_name_falls_back_to_the_waypoint_name() -> None:
    flight, mission_data, game = _fixture_with_real_waypoints(["", "", ""])
    flight.aircraft_type = SimpleNamespace(dcs_unit_type=SimpleNamespace(id="F-16C_50"))

    cartridge = build_viper_cartridge(flight, mission_data, game, "Test F-16C")

    nav_pts = json.loads(cartridge.to_json())["data"]["MPD"]["NAV_PTS"]
    assert [p["note"] for p in nav_pts[:2]] == ["TARGET", "LANDING"]
