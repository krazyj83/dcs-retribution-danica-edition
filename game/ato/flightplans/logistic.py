"""
game/ato/flightplans/logistic.py
Flight plan for a logistic warehouse-resupply mission.

Subclasses TransportFlightPlan because the route shape is identical:
  Depart -> Pickup (load supplies) -> Dropoff (unload) -> RTB

The Lua plugin (logistic_supply.lua) handles DCS warehouse transfers
when the aircraft lands at each stop. Works for player and AI, both
BLUEFOR and REDFOR.
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

    Why AirliftFlightPlan and not TransportFlightPlan?
    TransportFlightPlan does not exist as a standalone module in this
    codebase -- airlift.py is the concrete transport flight plan class.
    TransportFlightPlan is the abstract base inside airlift.py that
    AirliftFlightPlan already inherits from.
    """

    pass
