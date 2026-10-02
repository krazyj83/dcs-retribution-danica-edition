"""Era-correct units (game/livingworld/era.py) and map periods
(game/livingworld/theaterperiod.py)."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from game.dcs.groundunittype import GroundUnitType
from game.data.units import UnitClass
from game.livingworld.era import (
    in_service,
    in_service_only,
    not_in_service_reason,
    unit_year,
)
from game.livingworld.theaterperiod import THEATER_PERIODS, date_warning, period_for
from game.purchaseadapter import AircraftPurchaseAdapter, GroundUnitPurchaseAdapter
from game.settings import Settings


def _game(year: int, on: bool = True) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(restrict_units_by_date=on),
        current_day=datetime.date(year, 6, 12),
    )


class _Unit:
    """A unit type stand-in (hashable, like the real ones)."""

    def __init__(self, year: Any, name: str, **extra: Any) -> None:
        self.year_introduced = year
        self.display_name = name
        self.__dict__.update(extra)


def _unit(year: Any, name: str = "unit", **extra: Any) -> Any:
    return _Unit(year, name, **extra)


# --- the rule ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, year",
    [(1986, 1986), ("1986", 1986), ("N/A", None), ("No data.", None), (None, None)],
)
def test_unit_year(value: Any, year: Any) -> None:
    assert unit_year(_unit(value)) == year


def test_not_in_service_until_its_year() -> None:
    f16 = _unit(1991)
    assert not_in_service_reason(f16, _game(1985)) == "Not in service until 1991"
    assert in_service(f16, _game(1991))  # the year itself is fine
    assert in_service(f16, _game(2005))


def test_missing_years_and_the_setting_never_block() -> None:
    assert in_service(_unit("No data."), _game(1944))
    assert in_service(_unit(1991), _game(1985, on=False))
    assert in_service(_unit(1991), None)


def test_in_service_only_with_a_key() -> None:
    squadrons = [SimpleNamespace(aircraft=_unit(y)) for y in (1978, 1991, "N/A")]
    kept = in_service_only(squadrons, _game(1985), key=lambda s: s.aircraft)
    assert [s.aircraft.year_introduced for s in kept] == [1978, "N/A"]


def test_real_unit_data_has_years() -> None:
    m1a2 = GroundUnitType.named("M1A2 Abrams")
    assert unit_year(m1a2) == 1992
    assert not_in_service_reason(m1a2, _game(1985)) == "Not in service until 1992"
    assert in_service(m1a2, _game(2003))


# --- player purchases ----------------------------------------------------------


def test_ground_purchase_is_blocked_with_a_reason() -> None:
    game = _game(1985)
    coalition = SimpleNamespace(game=game, budget=1000)
    adapter = GroundUnitPurchaseAdapter(
        SimpleNamespace(has_ground_unit_source=lambda g: True), coalition, game  # type: ignore[arg-type]
    )
    new, old = _unit(1991, price=5), _unit(1978, price=5)
    assert adapter.blocked_reason(new) == "Not in service until 1991"
    assert not adapter.can_buy(new)
    assert adapter.can_buy(old)


def test_aircraft_purchase_is_blocked_with_a_reason() -> None:
    coalition = SimpleNamespace(game=_game(1985), budget=1000)
    cp = SimpleNamespace(coalition=coalition)
    adapter = AircraftPurchaseAdapter(cp)  # type: ignore[arg-type]
    squadron = SimpleNamespace(aircraft=_unit(1991, price=20))
    assert adapter.blocked_reason(squadron) == "Not in service until 1991"  # type: ignore[arg-type]


# --- AI purchases --------------------------------------------------------------


def test_ai_buys_only_units_in_service() -> None:
    from game.procurement import ProcurementAi

    tank_new = _unit(1991, "new tank", unit_class=UnitClass.TANK, price=5)
    tank_old = _unit(1965, "old tank", unit_class=UnitClass.TANK, price=5)
    apc_new = _unit(1995, "new APC", unit_class=UnitClass.APC, price=1)
    ai = object.__new__(ProcurementAi)
    ai.game = _game(1985)
    ai.faction = SimpleNamespace(  # type: ignore[assignment]
        frontline_units=[tank_new, tank_old, apc_new], artillery_units=[]
    )
    for _ in range(20):
        assert ai.affordable_ground_unit_of_class(100, UnitClass.TANK) is tank_old
    # No APC in service: falls back to another unit in service, never the new one.
    assert ai.affordable_ground_unit_of_class(100, UnitClass.APC) is tank_old


def test_ai_buys_nothing_when_nothing_is_in_service() -> None:
    from game.procurement import ProcurementAi

    ai = object.__new__(ProcurementAi)
    ai.game = _game(1950)
    ai.faction = SimpleNamespace(  # type: ignore[assignment]
        frontline_units=[_unit(1991, unit_class=UnitClass.TANK, price=5)],
        artillery_units=[],
    )
    assert ai.affordable_ground_unit_of_class(100, UnitClass.TANK) is None


# --- setting -------------------------------------------------------------------


def test_setting_is_on_by_default_and_old_saves_get_it() -> None:
    assert Settings().restrict_units_by_date is True
    state = dict(Settings().__dict__)
    state.pop("restrict_units_by_date")
    restored = Settings.__new__(Settings)
    restored.__setstate__(state)
    assert restored.restrict_units_by_date is True


# --- map periods ---------------------------------------------------------------


def test_ww2_and_cold_war_maps_warn_outside_their_period() -> None:
    warning = date_warning("Normandy", datetime.date(2005, 6, 1))
    assert warning is not None
    assert "Normandy 1944 depicts 1939–1946" in warning
    assert "Suggested: 06 Jun 1944" in warning
    assert date_warning("Normandy", datetime.date(1944, 6, 6)) is None
    assert date_warning("GermanyCW", datetime.date(1995, 1, 1)) is not None
    assert date_warning("GermanyCW", datetime.date(1985, 1, 1)) is None


def test_modern_maps_accept_the_jet_age() -> None:
    assert date_warning("Caucasus", datetime.date(1965, 1, 1)) is None
    assert date_warning("Caucasus", datetime.date(1944, 1, 1)) is not None
    assert date_warning("Unknown map", datetime.date(1900, 1, 1)) is None


def test_every_campaign_theater_has_a_period() -> None:
    import yaml

    theaters = set()
    for path in __import__("pathlib").Path("resources/campaigns").glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("theater"):
            theaters.add(data["theater"])
    assert theaters, "no campaigns found"
    assert theaters <= set(THEATER_PERIODS), theaters - set(THEATER_PERIODS)
    for period in THEATER_PERIODS.values():
        assert period.contains(period.suggested)
    assert period_for("Syria") is THEATER_PERIODS["Syria"]
