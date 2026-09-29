"""What happens to a base's stock when it changes hands.

Called from ControlPoint.capture, so it covers every capture: in the mission,
by the ground war, and the capture cheat.

    Weapon stores           all weapons set to 0 (they are lost or destroyed)
    Fuel                    stays as it is: the tanks are captured with the base
    Ammunition, supplies,   set to 0 for either side: the new owner has to
    troops                  ship them in

The base keeps its warehouse and weapon store list either way, so a base that
is lost and retaken keeps its fuel and shows its (empty) weapon stores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from game.logistics import LogisticsManager
    from game.theater.player import Player


def on_base_captured(
    logistics: LogisticsManager, cp: Any, new_owner: Player
) -> List[str]:
    """Apply the capture rules to the base's stock. Returns log lines."""
    from game.logistics import Warehouse, WarehouseCategory

    side = "BLUEFOR" if new_owner.is_blue else "REDFOR"
    log: List[str] = []

    inventory = logistics.get_weapon_inventory(cp.id)
    if inventory is not None:
        lost = sum(item.quantity for item in inventory.items.values())
        inventory.zero_all()
        if lost > 0:
            log.append(f"{cp.name} captured by {side}: {lost} weapons lost")

    from game.logistics import fit_to_owner

    warehouse = logistics.get_warehouse(cp.id)
    if warehouse is None:
        # A base whose stock was never tracked: the default tank farm.
        warehouse = Warehouse(cp_id=cp.id, cp_name=cp.name)
        logistics.add_warehouse(warehouse)
    fit_to_owner(warehouse, new_owner)
    for category in WarehouseCategory:
        if category is WarehouseCategory.FUEL:
            continue
        warehouse.stock[category].quantity = 0.0
    fuel = warehouse.stock[WarehouseCategory.FUEL].quantity
    log.append(
        f"{cp.name} captured by {side}: fuel kept ({fuel:.0f}), "
        "ammunition, supplies and troops lost"
    )
    return log
