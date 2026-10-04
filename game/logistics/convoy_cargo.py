"""Cargo trucks on player-drawn supply routes.

Every convoy on a player-drawn route (playerconvoygenerator.py) gets up to
``CARGO_TRUCKS_PER_CONVOY`` of its faction's cargo trucks on top of the
vehicles it borrows from the base reserve. The trucks aren't taken from any
base: they stand for the supply column itself. Each one hauls
``AMMO_PER_TRUCK`` ammunition and ``SUPPLIES_PER_TRUCK`` supplies from the
source base's warehouse, like the fuel trucks haul fuel (logistics/fuel.py):

    truck reached the route end    its load moves from the source warehouse to
                                   the destination's (what doesn't fit stays)
    truck destroyed                its load is lost from the source warehouse
    neither (still on the road)    nothing moves

The trucks of this mission are remembered on the LogisticsManager
(``_convoy_cargo_trucks``: unit name -> source and destination base ids)
until the results are processed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional
from uuid import UUID

if TYPE_CHECKING:
    from game import Game
    from game.dcs.groundunittype import GroundUnitType
    from game.factions.faction import Faction
    from game.theater import ControlPoint

logger = logging.getLogger(__name__)

#: Cargo trucks added to every player convoy.
CARGO_TRUCKS_PER_CONVOY = 4
#: Warehouse load of one truck (base capacity is 1,000 of each).
AMMO_PER_TRUCK = 25.0
SUPPLIES_PER_TRUCK = 25.0

#: Light vehicles in factions' logistics lists that are no cargo trucks.
_NOT_CARGO = ("jeep", "luv ", "utility", "uaz", "hmmwv", "humvee", "land rover 109")


def cargo_truck_type(faction: Faction) -> Optional[GroundUnitType]:
    """The faction's cargo truck: a logistics unit that is a truck and not a
    fuel tanker. Prefers types called "Truck"; None if the faction has none."""
    from game.logistics.fuel import is_fuel_truck

    candidates = [
        unit
        for unit in getattr(faction, "logistics_units", None) or ()
        if not is_fuel_truck(unit)
        and not any(word in str(unit).lower() for word in _NOT_CARGO)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda u: ("truck" not in str(u).lower(), str(u)))[0]


def _trucks(logistics: Any) -> Dict[str, Dict[str, Any]]:
    if not hasattr(logistics, "_convoy_cargo_trucks"):
        logistics._convoy_cargo_trucks = {}
    trucks: Dict[str, Dict[str, Any]] = logistics._convoy_cargo_trucks
    return trucks


def start_mission(game: Game) -> None:
    """A new mission is generated: forget the trucks of an earlier one."""
    logistics = getattr(game, "logistics", None)
    if logistics is not None:
        _trucks(logistics).clear()


def register(
    game: Game, names: Iterable[str], origin: ControlPoint, destination: ControlPoint
) -> None:
    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return
    for name in names:
        _trucks(logistics)[name] = {
            "origin": origin.id,
            "destination": destination.id,
        }


def _stock(game: Game, base: ControlPoint) -> Any:
    from game.logistics import new_base_warehouse

    warehouse = game.logistics.get_warehouse(base.id)
    if warehouse is None:
        warehouse = new_base_warehouse(base)
        game.logistics.add_warehouse(warehouse)
    return warehouse.stock


def _base(game: Game, cp_id: UUID) -> Optional[ControlPoint]:
    try:
        return game.theater.find_control_point_by_id(cp_id)
    except KeyError:
        return None


def settle(game: Game, killed: Iterable[str], arrived: Iterable[str]) -> List[str]:
    """Move or lose the trucks' loads. Returns debrief lines."""
    from game.logistics import WarehouseCategory
    from game.theater.player import Player

    logistics = getattr(game, "logistics", None)
    if logistics is None:
        return []
    trucks = _trucks(logistics)
    if not trucks:
        return []
    killed_set, arrived_set = set(killed), set(arrived)
    loads = {
        WarehouseCategory.AMMUNITION: AMMO_PER_TRUCK,
        WarehouseCategory.SUPPLIES: SUPPLIES_PER_TRUCK,
    }
    # (origin, destination) -> [delivered trucks, lost trucks]
    tally: Dict[tuple[UUID, UUID], List[int]] = {}
    moved: Dict[tuple[UUID, UUID], Dict[Any, float]] = {}
    for name, entry in trucks.items():
        origin = _base(game, entry["origin"])
        destination = _base(game, entry["destination"])
        if origin is None or origin.captured is not Player.BLUE:
            continue  # the source fell: its stock is no longer ours
        key = (entry["origin"], entry["destination"])
        counts = tally.setdefault(key, [0, 0])
        source = _stock(game, origin)
        if name in killed_set:
            counts[1] += 1
            for category, load in loads.items():
                item = source[category]
                item.quantity = max(0.0, item.quantity - load)
            continue
        if (
            name not in arrived_set
            or destination is None
            or destination is origin
            or destination.captured is not Player.BLUE
        ):
            continue
        counts[0] += 1
        target = _stock(game, destination)
        for category, load in loads.items():
            fits = min(
                load,
                source[category].quantity,
                max(0.0, target[category].capacity - target[category].quantity),
            )
            source[category].quantity -= fits
            target[category].quantity += fits
            moved.setdefault(key, {}).setdefault(category, 0.0)
            moved[key][category] += fits
    trucks.clear()

    lines: List[str] = []
    for (origin_id, destination_id), (delivered, lost) in tally.items():
        origin, destination = _base(game, origin_id), _base(game, destination_id)
        if origin is None:
            continue
        if delivered and destination is not None:
            got = moved.get((origin_id, destination_id), {})
            lines.append(
                f"{delivered} cargo truck(s) from {origin.name} delivered "
                f"{got.get(WarehouseCategory.AMMUNITION, 0.0):.0f} ammunition and "
                f"{got.get(WarehouseCategory.SUPPLIES, 0.0):.0f} supplies to "
                f"{destination.name}"
            )
        if lost:
            lines.append(
                f"{lost} cargo truck(s) from {origin.name} destroyed: "
                f"{lost * AMMO_PER_TRUCK:.0f} ammunition and "
                f"{lost * SUPPLIES_PER_TRUCK:.0f} supplies lost"
            )
    return lines
