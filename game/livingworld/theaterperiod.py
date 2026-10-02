"""The period each map depicts, for the New Game wizard's date warning.

A map's buildings, airfields and roads belong to an era: Normandy is the
summer of 1944, Germany Cold War the divided Germany of 1947-1991. A
campaign dated outside that period still works, it just looks wrong (jets
over 1944 villages, the Berlin Wall in 2010), so the wizard warns and
suggests a date inside the period. Maps of the present day accept any date
from the jet age on.

Keys are the campaign files' `theater:` names.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class TheaterPeriod:
    label: str
    first_year: int
    #: None: up to the present day.
    last_year: Optional[int] = None
    #: A date inside the period, suggested when the chosen one is outside it.
    suggested: datetime.date = datetime.date(2005, 6, 1)

    def contains(self, day: datetime.date) -> bool:
        if day.year < self.first_year:
            return False
        return self.last_year is None or day.year <= self.last_year

    @property
    def years(self) -> str:
        last = "today" if self.last_year is None else str(self.last_year)
        return f"{self.first_year}–{last}"


_PRESENT = 1950  # jet age onwards: modern towns and airfields

THEATER_PERIODS: Dict[str, TheaterPeriod] = {
    "Normandy": TheaterPeriod("Normandy 1944", 1939, 1946, datetime.date(1944, 6, 6)),
    "The Channel": TheaterPeriod(
        "The Channel 1944", 1939, 1946, datetime.date(1944, 6, 1)
    ),
    "MarianasWWII": TheaterPeriod(
        "Marianas WWII", 1941, 1946, datetime.date(1944, 6, 15)
    ),
    "GermanyCW": TheaterPeriod(
        "Cold War Germany", 1947, 1991, datetime.date(1985, 6, 1)
    ),
    "Falklands": TheaterPeriod(
        "South Atlantic", _PRESENT, None, datetime.date(1982, 5, 1)
    ),
    "Afghanistan": TheaterPeriod(
        "Afghanistan", _PRESENT, None, datetime.date(2011, 6, 1)
    ),
    "Caucasus": TheaterPeriod("Caucasus", _PRESENT, None, datetime.date(2008, 8, 8)),
    "Iraq": TheaterPeriod("Iraq", _PRESENT, None, datetime.date(2003, 3, 20)),
    "Kola": TheaterPeriod("Kola", _PRESENT, None, datetime.date(1988, 6, 1)),
    "MarianaIslands": TheaterPeriod(
        "Mariana Islands", _PRESENT, None, datetime.date(2016, 6, 1)
    ),
    "Nevada": TheaterPeriod("Nevada", _PRESENT, None, datetime.date(2010, 6, 1)),
    "Persian Gulf": TheaterPeriod(
        "Persian Gulf", _PRESENT, None, datetime.date(2011, 6, 1)
    ),
    "Sinai": TheaterPeriod("Sinai", _PRESENT, None, datetime.date(1973, 10, 6)),
    "Syria": TheaterPeriod("Syria", _PRESENT, None, datetime.date(2011, 6, 1)),
}


def period_for(theater: str) -> Optional[TheaterPeriod]:
    return THEATER_PERIODS.get(theater)


def date_warning(theater: str, day: datetime.date) -> Optional[str]:
    """A warning when `day` is outside the map's period, else None."""
    period = period_for(theater)
    if period is None or period.contains(day):
        return None
    return (
        f"{period.label} depicts {period.years}; {day.year} is outside it. "
        f"Units will work, but towns and airfields won't match the date. "
        f"Suggested: {period.suggested:%d %b %Y}."
    )
