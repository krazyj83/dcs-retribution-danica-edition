"""
game/missiongenerator/logistic_plugin_injector.py  — NEW FILE

Generates the Lua data table that tells logistic_supply.lua which aircraft
groups are logistic flights and what supplies they are carrying.

Called from missiongenerator.py during mission generation. The output is
injected as an inline DO SCRIPT trigger before the logistic_supply.lua
handler script so the handler can read the table on mission start.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game.ato.package import Package


def build_logistic_mission_table(packages: list[Package]) -> str:
    """
    Generates the Lua source string for RETRIBUTION_LOGISTIC_MISSIONS.

    This table is read by logistic_supply.lua at mission start to identify
    which aircraft groups are logistic flights and what they're carrying.

    Args:
        packages: All packages in the ATO for this turn (both coalitions).
                  We filter internally for FlightType.LOGISTIC.

    Returns:
        A string of Lua code ready to be passed to a DoScript trigger.
        Always returns a valid Lua statement even if there are no logistic
        flights this turn (returns an empty table so the handler doesn't crash).
    """
    from game.ato.flighttype import FlightType  # avoid circular import at module level

    entries: list[str] = []

    for package in packages:
        for flight in package.flights:
            if flight.flight_type != FlightType.LOGISTIC:
                continue

            payload = getattr(flight, "logistic_payload", None)
            if payload is None:
                continue

            fuel_kg    = payload.get("fuel_kg", 0)
            ammo_items = payload.get("ammo_items", [])
            origin     = payload.get("origin_base_name", "")
            dest       = payload.get("dest_base_name", "")

            # Determine which DCS coalition side constant to use
            # coalition.player is True for blue
            coalition_lua = (
                "coalition.side.BLUE"
                if getattr(flight.squadron, "player", True)
                else "coalition.side.RED"
            )

            # Build the nested ammo_items Lua table
            if ammo_items:
                ammo_lines = ",\n".join(
                    f'          {{ item = "{item["item"]}", count = {item["count"]} }}'
                    for item in ammo_items
                )
                ammo_lua = "{\n" + ammo_lines + "\n        }"
            else:
                ammo_lua = "{}"

            # group_name matches the pydcs group name set by the aircraft generator
            group_name = getattr(flight, "group_name", "") or getattr(flight, "unit_id", "")

            entry = (
                f"  {{\n"
                f"    group_name = \"{group_name}\",\n"
                f"    coalition  = {coalition_lua},\n"
                f"    origin     = \"{origin}\",\n"
                f"    dest       = \"{dest}\",\n"
                f"    fuel_kg    = {int(fuel_kg)},\n"
                f"    ammo_items = {ammo_lua},\n"
                f"  }}"
            )
            entries.append(entry)

    if not entries:
        # Safe empty table — handler won't crash, just logs and exits early
        return "RETRIBUTION_LOGISTIC_MISSIONS = {}"

    joined = ",\n".join(entries)
    return f"RETRIBUTION_LOGISTIC_MISSIONS = {{\n{joined}\n}}"
