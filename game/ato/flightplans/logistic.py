"""
game/ato/flightplans/logistic.py  — NEW FILE

Flight plan for a logistic warehouse-resupply mission.

Subclasses TransportFlightPlan because the route shape is identical:
  Depart → Pickup (load supplies) → Dropoff (unload) → RTB

The Lua plugin (logistic_supply.lua) handles DCS warehouse transfers
when the aircraft lands at each stop. Works for player and AI, both
BLUEFOR and REDFOR.
"""

from __future__ import annotations

from game.ato.flightplans.transport import TransportFlightPlan


class LogisticFlightPlan(TransportFlightPlan):
    """
    Flight plan for a LOGISTIC resupply mission.

    Route shape is identical to Transport/Airlift. The distinction is:
      - Transport moves *units* (troops, vehicles)
      - Logistic moves *supplies* (fuel, ammo) via DCS warehouse API

    All waypoint generation, timing, TOT calculation, and ROE settings
    are inherited from TransportFlightPlan — nothing needs overriding yet.

    If you later want logistic flights to use different cruise altitude
    or speed from airlift, override cruise_speed() and cruise_altitude()
    here following the pattern in other FlightPlan subclasses.
    """
    pass
