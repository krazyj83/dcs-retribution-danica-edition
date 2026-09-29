"""REDFOR warehouse fuel and ammunition.

With the "REDFOR logistics" setting on (default), every REDFOR base keeps a
warehouse like BLUEFOR's, and it decides how many sorties REDFOR can fly:

* **Use.** After each mission, every REDFOR aircraft in it uses fuel from its
  departure base (same amount as BLUEFOR, logistics/fuel.py) and combat
  aircraft use ammunition: AMMO_PER_A2G_AIRCRAFT for air-to-ground tasks,
  AMMO_PER_A2A_AIRCRAFT for air-to-air ones.
* **Grounding.** When REDFOR plans a turn, packages that would need more fuel
  or ammunition than their base holds are cancelled, the lowest-priority
  (last planned) first. Transport, ferry and air assault packages are never
  cancelled: they are how REDFOR moves things around. Each cancelled package
  is reported as intel in the turn's messages.
* **Resupply.** At the end of every turn each REDFOR base gets back what its
  sorties used plus the setting's fuel per turn (two thirds of that in
  ammunition), scaled by what is left of REDFOR's fuel and ammo depots across
  the map. With every depot standing a base keeps flying at its current rate;
  with half the fuel depot buildings destroyed it only gets half its fuel
  back, and its stock (and then its sorties) run down.
* REDFOR warehouses hold RED_CAPACITY fuel, ammunition and supplies (used for
  repairs, logistics/repairs.py) and start full: a
  busy REDFOR airfield flies 600-800 fuel worth of sorties a turn.
* Carriers and other ships (fleet control points) are left out: they are
  resupplied at sea and their sorties are never grounded.
* **Losses.** Destroyed depots near a base cost that base stock
  (logistics/debrief_hook.py, both sides), and REDFOR fuel trucks in road
  convoys carry fuel forward and lose it when destroyed (logistics/fuel.py).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Tuple

from game.logistics import RED_CAPACITY

if TYPE_CHECKING:
    from game import Game

logger = logging.getLogger(__name__)

AMMO_PER_A2G_AIRCRAFT = 4.0
AMMO_PER_A2A_AIRCRAFT = 1.0
#: Ammunition resupply per turn, as a fraction of the fuel resupply setting.
AMMO_RESUPPLY_FRACTION = 2 / 3
DEFAULT_FUEL_PER_TURN = 60

EPSILON = 0.01


def enabled(game: Any) -> bool:
    settings = getattr(game, "settings", None)
    return bool(getattr(settings, "redfor_logistics", False))


def _protected(flight: Any) -> bool:
    from game.ato.flighttype import FlightType

    return flight.flight_type in (
        FlightType.TRANSPORT,
        FlightType.FERRY,
        FlightType.AIR_ASSAULT,
        FlightType.LOGISTIC,
        FlightType.PRETENSE_CARGO,
    )


def ammo_per_aircraft(flight_type: Any) -> float:
    if flight_type.is_air_to_ground:
        return AMMO_PER_A2G_AIRCRAFT
    if flight_type.is_air_to_air:
        return AMMO_PER_A2A_AIRCRAFT
    return 0.0


def flight_demand(flight: Any) -> Tuple[float, float]:
    """(fuel, ammunition) one flight uses from its departure base."""
    from game.logistics.fuel import fuel_per_aircraft

    count = flight.count
    return (
        count * fuel_per_aircraft(flight.unit_type),
        count * ammo_per_aircraft(flight.flight_type),
    )


def is_red_land_base(cp: Any) -> bool:
    """A REDFOR base that keeps a warehouse: not off-map, not a ship."""
    from game.logistics import keeps_warehouse

    return bool(cp.captured.is_red) and keeps_warehouse(cp)


def ensure_red_warehouses(game: Any) -> None:
    """Every REDFOR base gets a full warehouse if it has none yet."""
    from game.logistics import new_base_warehouse
    from game.theater.player import Player

    logistics = game.logistics
    for cp in game.theater.controlpoints:
        if not is_red_land_base(cp):
            continue
        if logistics.get_warehouse(cp.id) is None:
            logistics.add_warehouse(new_base_warehouse(cp, Player.RED))


def _stock(game: Any, cp: Any) -> Any:
    from game.logistics import WarehouseCategory

    if getattr(cp, "is_fleet", False):
        return None
    warehouse = game.logistics.get_warehouse(cp.id)
    if warehouse is None:
        return None
    return (
        warehouse.stock[WarehouseCategory.FUEL],
        warehouse.stock[WarehouseCategory.AMMUNITION],
    )


# ── Use after the mission ─────────────────────────────────────────────────


def use_red_sortie_stock(game: Any) -> List[str]:
    """Take the fuel and ammunition of every REDFOR aircraft just flown."""
    red = getattr(game, "red", None)
    if not enabled(game) or red is None:
        return []
    for warehouse in game.logistics.warehouses_for_coalition("red"):
        warehouse.fuel_used_last_mission = 0.0
        warehouse.ammo_used_last_mission = 0.0

    fuel_used: Dict[Any, float] = defaultdict(float)
    ammo_used: Dict[Any, float] = defaultdict(float)
    bases: Dict[Any, Any] = {}
    for package in red.ato.packages:
        for flight in package.flights:
            base = getattr(flight, "departure", None)
            if base is None or not base.captured.is_red:
                continue
            fuel, ammo = flight_demand(flight)
            bases[base.id] = base
            fuel_used[base.id] += fuel
            ammo_used[base.id] += ammo

    log: List[str] = []
    for base_id, base in bases.items():
        stock = _stock(game, base)
        if stock is None:
            continue
        fuel_item, ammo_item = stock
        fuel_item.quantity = max(0.0, fuel_item.quantity - fuel_used[base_id])
        ammo_item.quantity = max(0.0, ammo_item.quantity - ammo_used[base_id])
        warehouse = game.logistics.get_warehouse(base.id)
        warehouse.fuel_used_last_mission = fuel_used[base_id]
        warehouse.ammo_used_last_mission = ammo_used[base_id]
        log.append(
            f"REDFOR {base.name}: sorties used {fuel_used[base_id]:.0f} fuel and "
            f"{ammo_used[base_id]:.0f} ammunition; {fuel_item.quantity:.0f} fuel, "
            f"{ammo_item.quantity:.0f} ammunition left"
        )
    for line in log:
        logger.info(line)
    return log


# ── Grounding at planning ─────────────────────────────────────────────────


def _demand_by_base(packages: Iterable[Any]) -> Dict[Any, List[Any]]:
    """Base id -> [base, fuel, ammunition] the packages need."""
    demand: Dict[Any, List[Any]] = {}
    for package in packages:
        for flight in package.flights:
            base = getattr(flight, "departure", None)
            if base is None:
                continue
            fuel, ammo = flight_demand(flight)
            entry = demand.setdefault(base.id, [base, 0.0, 0.0])
            entry[1] += fuel
            entry[2] += ammo
    return demand


def apply_supply_limits(game: Any, ato: Any) -> List[str]:
    """Cancel REDFOR packages their bases can't fuel or arm. Returns log lines."""
    if not enabled(game):
        return []
    ensure_red_warehouses(game)
    sync_warehouse_sides(game)
    grounded: Dict[Tuple[str, str], int] = defaultdict(int)

    while True:
        short: Dict[Any, str] = {}
        for base_id, (base, fuel, ammo) in _demand_by_base(ato.packages).items():
            stock = _stock(game, base)
            if stock is None or not base.captured.is_red:
                continue
            fuel_item, ammo_item = stock
            if fuel > fuel_item.quantity + EPSILON:
                short[base_id] = "fuel"
            elif ammo > ammo_item.quantity + EPSILON:
                short[base_id] = "ammunition"
        if not short:
            break

        victim = None
        for package in reversed(ato.packages):
            if any(_protected(f) for f in package.flights):
                continue
            for flight in package.flights:
                base = getattr(flight, "departure", None)
                reason = short.get(getattr(base, "id", None))
                if reason is None:
                    continue
                if reason == "ammunition" and flight_demand(flight)[1] <= 0:
                    continue
                victim = (package, base, reason)
                break
            if victim is not None:
                break
        if victim is None:
            break  # only protected packages left over budget
        package, base, reason = victim
        grounded[(base.name, reason)] += 1
        ato.remove_package(package)

    # For the base's Intel tab: what was grounded when this turn was planned.
    logistics = game.logistics
    turn = getattr(game, "turn", 0)
    record: Dict[str, Tuple[int, int, str]] = {}
    for (base_name, reason), count in grounded.items():
        _, earlier, _ = record.get(base_name, (turn, 0, reason))
        record[base_name] = (turn, earlier + count, reason)
    logistics._red_grounded = record

    log: List[str] = []
    for (base_name, reason), count in sorted(grounded.items()):
        line = f"REDFOR {base_name}: {count} package(s) grounded, not enough {reason}"
        log.append(line)
        logger.info(line)
        if hasattr(game, "message"):
            game.message(
                f"Intel: REDFOR short of {reason} at {base_name}",
                f"{count} planned enemy package(s) grounded this turn.",
            )
    from game.logistics.turn_report import add_to_latest

    add_to_latest(logistics, "enemy", log)
    return log


# ── Resupply at the end of the turn ───────────────────────────────────────


def depot_factor(game: Any, category: str) -> float:
    """Alive fraction of REDFOR depot buildings of this category (1.0: none)."""
    total = alive = 0
    for tgo in game.theater.ground_objects:
        if getattr(tgo, "category", None) != category:
            continue
        if not tgo.control_point.captured.is_red:
            continue
        for unit in tgo.units:
            total += 1
            alive += 1 if unit.alive else 0
    return 1.0 if total == 0 else alive / total


def resupply(game: Any) -> List[str]:
    """End of turn: every REDFOR base gets its resupply. Once per turn."""
    from game.logistics import WarehouseCategory

    if not enabled(game):
        return []
    logistics = game.logistics
    turn = getattr(game, "turn", 0)
    if getattr(logistics, "_red_resupply_turn", None) == turn:
        return []
    logistics._red_resupply_turn = turn

    ensure_red_warehouses(game)
    sync_warehouse_sides(game)
    per_turn = float(
        getattr(game.settings, "redfor_fuel_per_turn", DEFAULT_FUEL_PER_TURN)
    )
    fuel_factor = depot_factor(game, "fuel")
    ammo_factor = depot_factor(game, "ammo")

    for warehouse in logistics.warehouses_for_coalition("red"):
        fuel_item = warehouse.stock[WarehouseCategory.FUEL]
        ammo_item = warehouse.stock[WarehouseCategory.AMMUNITION]
        used_fuel = float(getattr(warehouse, "fuel_used_last_mission", 0.0) or 0.0)
        used_ammo = float(getattr(warehouse, "ammo_used_last_mission", 0.0) or 0.0)
        fuel_add = fuel_factor * (per_turn + used_fuel)
        ammo_add = ammo_factor * (per_turn * AMMO_RESUPPLY_FRACTION + used_ammo)
        fuel_item.quantity = min(fuel_item.capacity, fuel_item.quantity + fuel_add)
        ammo_item.quantity = min(ammo_item.capacity, ammo_item.quantity + ammo_add)
        # Supplies only go to repairs (logistics/repairs.py).
        supplies_item = warehouse.stock[WarehouseCategory.SUPPLIES]
        supplies_item.quantity = min(
            supplies_item.capacity,
            supplies_item.quantity + ammo_factor * per_turn * AMMO_RESUPPLY_FRACTION,
        )

    line = (
        f"REDFOR resupply: {fuel_factor:.0%} of fuel used back plus "
        f"{fuel_factor * per_turn:.0f} ({fuel_factor:.0%} of fuel depots standing), "
        f"{ammo_factor:.0%} of ammunition used back plus "
        f"{ammo_factor * per_turn * AMMO_RESUPPLY_FRACTION:.0f} "
        f"({ammo_factor:.0%} of ammo depots standing)"
    )
    logger.info(line)
    return [line]


def sync_warehouse_sides(game: Any) -> None:
    """Keep each warehouse's coalition in step with its base's owner."""
    for cp in game.theater.controlpoints:
        warehouse = game.logistics.get_warehouse(cp.id)
        if warehouse is not None:
            warehouse.coalition = "blue" if cp.captured.is_blue else "red"


# ── Intel estimate (base window, Intel tab) ───────────────────────────────


def intel_estimate(game: Any, cp: Any) -> List[Tuple[str, str, str]]:
    """(label, estimate, colour) rows for a REDFOR base's Intel tab.

    Stock is only known from recon (logistics/intel.py); without a recent
    report the rows say so. [] when REDFOR logistics is off.
    """
    from game.logistics.intel import age_text, estimate, intel_for

    if not enabled(game) or not cp.captured.is_red or getattr(cp, "is_fleet", False):
        return []
    rows: List[Tuple[str, str, str]] = []
    found = intel_for(game, cp)
    if found is None:
        rows.append(
            (
                "Stock",
                "Unknown: fly near the base (30 km) to update",
                "#95a5a6",
            )
        )
    else:
        report, age = found
        rows.append(("Fuel", *estimate(report.fuel)))
        rows.append(("Ammunition", *estimate(report.ammunition)))
        rows.append(("Source", age_text(age), "#95a5a6"))
    grounded = getattr(game.logistics, "_red_grounded", {}).get(cp.name)
    if grounded and grounded[0] == getattr(game, "turn", 0):
        rows.append(
            (
                "This turn",
                f"{grounded[1]} package(s) grounded (short of {grounded[2]})",
                "#f39c12",
            )
        )
    return rows
