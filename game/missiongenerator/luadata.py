"""Data tables the fork hands to its mission scripts.

The campaign writes plain Lua tables (dcsRetributionWarehouses,
dcsRetributionNaval, dcsRetributionPlayerConvoys, dcsRetributionCargo) into
mission start triggers. The scripts in resources/plugins read them when they
load, so LuaGenerator keeps every trigger whose comment starts with
DATA_TRIGGER_PREFIX ahead of the plugin scripts.

One helper writes them all, so each table is escaped and ordered the same way.
"""

from __future__ import annotations

import math
from typing import Any

from dcs import Mission
from dcs.action import DoScript
from dcs.translation import String
from dcs.triggers import TriggerStart

#: Comment prefix of the start triggers that set the fork's data tables.
DATA_TRIGGER_PREFIX = "Set DCS Retribution"


def to_lua(value: Any) -> str:
    """A Python value (dict/list/str/number/bool/None) as a Lua literal."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # repr() would give "inf"/"nan", which Lua reads as undefined variables.
        if math.isnan(value):
            return "(0/0)"
        if math.isinf(value):
            return "math.huge" if value > 0 else "-math.huge"
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "")
        )
        return f'"{escaped}"'
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"[{to_lua(str(k))}] = {to_lua(v)}" for k, v in value.items())
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(to_lua(v) for v in value) + "}"
    raise TypeError(f"Cannot write {type(value).__name__} to Lua")


def inject_data_table(mission: Mission, name: str, value: Any, what: str) -> None:
    """Set the global Lua table `name` at mission start.

    `what` names the data in the trigger comment ("warehouse" gives
    "Set DCS Retribution warehouse data").
    """
    trigger = TriggerStart(comment=f"{DATA_TRIGGER_PREFIX} {what} data")
    trigger.add_action(DoScript(String(f"{name} = {to_lua(value)}")))
    mission.triggerrules.triggers.append(trigger)
