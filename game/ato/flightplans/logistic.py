"""
game/ato/flightplans/logistic.py

Flight plan for a LOGISTIC warehouse-resupply mission.

Route shape is identical to AirliftFlightPlan:
  Depart -> Pickup (load supplies) -> Dropoff (unload) -> RTB

The Lua plugin (logistic_supply.lua) handles DCS warehouse transfers
when the aircraft lands at each stop. Works for player and AI, both
BLUEFOR and REDFOR.

Why AirliftFlightPlan and not TransportFlightPlan?
transport.py does not exist in this codebase. AirliftFlightPlan in
airlift.py is the concrete transport flight plan used by TRANSPORT,
and is the correct base for LOGISTIC too since the route is identical.
"""
from __future__ import annotations

from game.ato.flightplans.airlift import AirliftFlightPlan


class LogisticFlightPlan(AirliftFlightPlan):
    """
    Flight plan for a LOGISTIC resupply mission.

    Route shape is identical to Transport/Airlift. The distinction is:
      - Transport moves *units* (troops, vehicles)
      - Logistic moves *supplies* (fuel, ammo) via DCS warehouse API

    All waypoint generation, timing, TOT calculation, and ROE settings
    are inherited from AirliftFlightPlan -- nothing needs overriding yet.

    If you later want logistic flights to use different cruise altitude
    or speed from airlift, override cruise_speed() and cruise_altitude()
    here following the pattern in other FlightPlan subclasses.
    """
    pass
