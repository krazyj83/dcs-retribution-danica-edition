"""Era-correct units: nothing can be bought before it entered service.

Every unit file in resources/units may give the year the unit (or variant)
was introduced:

    introduced: 1986

With "Restrict unit purchases by date" on, a unit whose year is later than the
current campaign date (game.current_day, which moves with the campaign) can't
be bought by the player or by the AI. Units already owned stay. Units without a
year in their file (about half the ground units and most ships) are always
allowed: missing data never blocks anything.

    campaign date 12 Jun 1985
    F-16C bl.50   introduced 1991  -> "Not in service until 1991"
    F-16A         introduced 1978  -> buyable
    M1097 Avenger no year           -> buyable
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, TypeVar

T = TypeVar("T")


def unit_year(unit_type: Any) -> Optional[int]:
    """The year the unit entered service, or None when the data has none.

    The unit loaders store an int, or "N/A" / "No data." when the file has no
    usable year.
    """
    value = getattr(unit_type, "year_introduced", None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def restricts(game: Any) -> bool:
    """Is the era filter on for this game?"""
    settings = getattr(game, "settings", None)
    return bool(getattr(settings, "restrict_units_by_date", False))


def campaign_year(game: Any) -> int:
    return int(game.current_day.year)


def not_in_service_reason(unit_type: Any, game: Any) -> Optional[str]:
    """Why the unit can't be bought yet, or None if it can."""
    if game is None or not restricts(game):
        return None
    year = unit_year(unit_type)
    if year is None or year <= campaign_year(game):
        return None
    return f"Not in service until {year}"


def in_service(unit_type: Any, game: Any) -> bool:
    return not_in_service_reason(unit_type, game) is None


def in_service_only(units: Iterable[T], game: Any, key: Any = None) -> List[T]:
    """The units (or squadrons etc., with `key` giving the unit type) that
    can be bought now."""
    return [u for u in units if in_service(key(u) if key else u, game)]
