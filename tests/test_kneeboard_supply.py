"""The Base Supply kneeboard page (game/logistics/kneeboard_supply.py and
BaseSupplyPage in game/missiongenerator/kneeboard.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from game.logistics import (
    LogisticsManager,
    WarehouseCategory,
    WeaponInventory,
    new_base_warehouse,
)
from game.logistics import kneeboard_supply
from game.logistics.kneeboard_supply import (
    MAX_SUMMARY_NAMES,
    MAX_WEAPON_ROWS,
    BaseSupplyInfo,
    WeaponLine,
    flight_bases,
    short_name,
)
from game.theater.player import Player


def _cp(name: str, side: Player = Player.BLUE, **extra: Any) -> Any:
    return SimpleNamespace(id=uuid4(), name=name, captured=side, **extra)


def _runway(name: str) -> Any:
    return SimpleNamespace(airfield_name=name)


@pytest.fixture
def setup(monkeypatch: Any) -> Any:
    # The F/A-18C can carry these three; anything else in store is left out.
    monkeypatch.setattr(
        kneeboard_supply,
        "aircraft_weapon_ids",
        lambda aircraft: {"{AIM120C}", "{GBU12}", "{AGM88}"},
    )
    home, other, ship = _cp("Kutaisi"), _cp("Senaki"), _cp("CVN-74", is_fleet=True)
    enemy = _cp("Sochi", Player.RED)
    lm = LogisticsManager()
    for cp in (home, other):
        lm.add_warehouse(new_base_warehouse(cp))
    inv = WeaponInventory(cp_id=home.id, cp_name=home.name)
    inv.add_item("{AIM120C}", "AIM-120C", "Air-to-Air", quantity=34)
    inv.add_item("{GBU12}", "GBU-12", "Bomb", quantity=6)
    inv.add_item("{AGM88}", "AGM-88C", "Air-to-Ground Missile", quantity=0)
    inv.add_item("{R27}", "R-27ER", "Air-to-Air", quantity=40)  # not for this jet
    lm.set_weapon_inventory(inv)
    game = SimpleNamespace(
        logistics=lm,
        settings=SimpleNamespace(logistics_unlimited_fuel=False),
        theater=SimpleNamespace(controlpoints=[home, other, ship, enemy]),
    )
    return SimpleNamespace(game=game, home=home, other=other, ship=ship, enemy=enemy)


def _flight(departure: str, arrival: str, divert: Any = None) -> Any:
    return SimpleNamespace(
        departure=_runway(departure),
        arrival=_runway(arrival),
        divert=_runway(divert) if divert else None,
        aircraft_type=SimpleNamespace(display_name="F/A-18C"),
        squadron=SimpleNamespace(location=None),
    )


def test_departure_base_stock_and_this_aircrafts_weapons(setup: Any) -> None:
    ammo = setup.game.logistics.get_warehouse(setup.home.id).stock[
        WarehouseCategory.AMMUNITION
    ]
    ammo.quantity = 150  # 15%: critical

    (base,) = flight_bases(setup.game, _flight("Kutaisi", "Kutaisi"))

    assert (base.role, base.name, base.has_warehouse) == ("Departure", "Kutaisi", True)
    assert [(s.label, s.status) for s in base.stock] == [
        ("Fuel", "ok"),
        ("Ammunition", "critical"),
        ("Supplies", "ok"),
    ]
    assert base.stock[1].percent == "15%"
    assert "ammunition 15%" in base.warnings
    # Empty first, then low, then the rest; R-27ER isn't for this aircraft.
    assert [(w.name, w.quantity, w.flag) for w in base.weapons or []] == [
        ("AGM-88C", 0, "EMPTY"),
        ("GBU-12", 6, "LOW"),
        ("AIM-120C", 34, ""),
    ]


def test_arrival_and_divert_are_listed_once_each(setup: Any) -> None:
    bases = flight_bases(setup.game, _flight("Kutaisi", "Senaki", "Kutaisi"))
    assert [(b.role, b.name) for b in bases] == [
        ("Departure", "Kutaisi"),
        ("Arrival", "Senaki"),
    ]
    assert bases[1].weapons is None  # Senaki's stores were never synced


def test_ships_have_no_warehouse_and_enemy_bases_are_left_out(setup: Any) -> None:
    bases = flight_bases(setup.game, _flight("CVN-74", "Sochi"))
    assert [(b.role, b.name, b.has_warehouse) for b in bases] == [
        ("Departure", "CVN-74", False)
    ]


def test_unlimited_fuel_is_shown_as_such(setup: Any) -> None:
    setup.game.settings.logistics_unlimited_fuel = True
    (base,) = flight_bases(setup.game, _flight("Kutaisi", "Kutaisi"))
    assert base.stock[0].status == "unlimited"


def test_long_weapon_lists_are_cut(setup: Any, monkeypatch: Any) -> None:
    inv = setup.game.logistics.get_weapon_inventory(setup.home.id)
    ids = set()
    for i in range(MAX_WEAPON_ROWS + 5):
        inv.add_item(f"{{W{i}}}", f"Weapon {i:02d}", "Bomb", quantity=20)
        ids.add(f"{{W{i}}}")
    monkeypatch.setattr(kneeboard_supply, "aircraft_weapon_ids", lambda a: ids)
    (base,) = flight_bases(setup.game, _flight("Kutaisi", "Kutaisi"))
    assert len(base.weapons or []) == MAX_WEAPON_ROWS
    assert base.hidden_weapons == 5


def test_arrival_lists_only_empty_and_low_weapons(setup: Any) -> None:
    _, arrival = flight_bases(setup.game, _flight("Senaki", "Kutaisi"))
    assert [w.name for w in arrival.weapons or []] == ["AGM-88C", "GBU-12"]
    assert arrival.summary == "Empty: AGM-88C. Low: GBU-12 (6)."


def test_summary_line() -> None:
    def info(*weapons: WeaponLine) -> BaseSupplyInfo:
        return BaseSupplyInfo("Arrival", "X", weapons=list(weapons))

    assert info().summary == "No empty or low weapons."
    assert info(WeaponLine("GBU-12", 3, "LOW")).summary == "Low: GBU-12 (3)."
    many = [WeaponLine(f"W{i}", 0, "EMPTY") for i in range(MAX_SUMMARY_NAMES + 2)]
    assert info(*many).summary.endswith("W5. +2 more.")


def test_short_name() -> None:
    assert short_name("AIM-120C", 34) == "AIM-120C"
    long = "AGM-88C HARM - High Speed Anti-Radiation Missile"
    assert short_name(long, 34) == "AGM-88C HARM - High Speed Anti-..."
    assert len(short_name(long, 34)) == 34


# --- the page ------------------------------------------------------------------


@pytest.fixture
def kneeboard_font() -> None:
    """The pages are drawn in Courier New Bold, which Windows has; skip
    elsewhere unless courbd.ttf is put next to the tests' working folder."""
    from PIL import ImageFont

    try:
        ImageFont.truetype("courbd.ttf", 10)
    except OSError:
        pytest.skip("courbd.ttf (Windows font) not available")


def _page(setup: Any, flight: Any) -> Any:
    from game.missiongenerator.kneeboard import BaseSupplyPage

    flight.callsign = "Enfield 1"
    flight.custom_name = None
    return BaseSupplyPage(flight, setup.game, dark_kneeboard=False)


def test_page_draws_both_bases(
    setup: Any, tmp_path: Path, kneeboard_font: None
) -> None:
    path = tmp_path / "supply.png"
    _page(setup, _flight("Kutaisi", "Senaki")).write(path)

    assert path.exists() and path.stat().st_size > 0
    text = path.with_suffix(".txt").read_text("utf8")
    assert "Enfield 1 Base Supply" in text
    assert "Departure: Kutaisi" in text and "Arrival: Senaki" in text
    assert "AGM-88C" in text and "EMPTY" in text
    assert "Weapons for the F/A-18C" in text
    assert "Weapon stores not synced yet" in text  # Senaki


def test_page_without_friendly_bases(
    setup: Any, tmp_path: Path, kneeboard_font: None
) -> None:
    path = tmp_path / "supply.png"
    _page(setup, _flight("Sochi", "Sochi")).write(path)
    assert "No friendly base" in path.with_suffix(".txt").read_text("utf8")


def test_page_only_for_blue_flights_with_the_setting_on() -> None:
    from game.missiongenerator.kneeboard import KneeboardGenerator

    generator = object.__new__(KneeboardGenerator)
    settings = SimpleNamespace(kneeboard_base_supply_page=True)
    generator.game = SimpleNamespace(settings=settings)  # type: ignore[assignment]
    blue = SimpleNamespace(friendly=Player.BLUE)
    red = SimpleNamespace(friendly=Player.RED)

    assert generator._wants_base_supply_page(blue)  # type: ignore[arg-type]
    assert not generator._wants_base_supply_page(red)  # type: ignore[arg-type]
    settings.kneeboard_base_supply_page = False
    assert not generator._wants_base_supply_page(blue)  # type: ignore[arg-type]
