"""Ammunition losses from destroyed ground objects in the logistics debrief."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List
from uuid import uuid4

from game.logistics import LogisticsManager, Warehouse, WarehouseCategory
from game.logistics.debrief_hook import (
    AMMO_LOSS_PER_DEPOT_UNIT,
    sam_site_ammo_loss,
    update_logistics_from_debriefing,
)

START_AMMO = 1000.0


def _base(name: str = "Kutaisi") -> Any:
    return SimpleNamespace(id=uuid4(), name=name)


def _site(
    cp: Any, category: str, has_aa: bool = False, name: str = "SAM1", size: int = 10
) -> Any:
    return SimpleNamespace(
        unit_count=size,
        control_point=cp,
        category=category,
        has_aa=has_aa,
        name=name,
        is_ammo_depot=category == "ammo",
    )


def _debrief(logistics: LogisticsManager, dead_units_of: List[Any]) -> Any:
    losses = [
        SimpleNamespace(theater_unit=SimpleNamespace(ground_object=tgo))
        for tgo in dead_units_of
    ]
    return SimpleNamespace(
        game=SimpleNamespace(logistics=logistics),
        ground_object_losses=losses,
        base_captures=[],
    )


def _setup(*bases: Any) -> LogisticsManager:
    logistics = LogisticsManager()
    for cp in bases:
        wh = Warehouse(cp_id=cp.id, cp_name=cp.name)
        wh.stock[WarehouseCategory.AMMUNITION].quantity = START_AMMO
        logistics.add_warehouse(wh)
    return logistics


def _ammo(logistics: LogisticsManager, cp: Any) -> float:
    wh = logistics.get_warehouse(cp.id)
    assert wh is not None
    return wh.stock[WarehouseCategory.AMMUNITION].quantity


def test_knocked_out_sam_site_costs_ammo_once() -> None:
    cp = _base()
    logistics = _setup(cp)
    sam = _site(cp, "aa", has_aa=False)
    # Eight vehicles of the same site destroyed: charged once.
    log = update_logistics_from_debriefing(_debrief(logistics, [sam] * 8))
    assert _ammo(logistics, cp) == START_AMMO - sam_site_ammo_loss(10)
    assert len(log) == 1
    assert "SAM site SAM1 (10 vehicles) knocked out" in log[0]


def test_damaged_sam_site_costs_nothing() -> None:
    cp = _base()
    logistics = _setup(cp)
    sam = _site(cp, "aa", has_aa=True)
    log = update_logistics_from_debriefing(_debrief(logistics, [sam, sam]))
    assert _ammo(logistics, cp) == START_AMMO
    assert log == []


def test_each_knocked_out_site_is_charged() -> None:
    cp = _base()
    logistics = _setup(cp)
    sam1 = _site(cp, "aa", name="SAM1")
    sam2 = _site(cp, "aa", name="SAM2")
    update_logistics_from_debriefing(_debrief(logistics, [sam1, sam2, sam1]))
    assert _ammo(logistics, cp) == START_AMMO - 2 * sam_site_ammo_loss(10)


def test_sam_loss_charged_to_owning_base() -> None:
    home = _base("Kutaisi")
    other = _base("Senaki")
    logistics = _setup(home, other)
    update_logistics_from_debriefing(_debrief(logistics, [_site(home, "aa")]))
    assert _ammo(logistics, home) == START_AMMO - sam_site_ammo_loss(10)
    assert _ammo(logistics, other) == START_AMMO


def test_ammo_depot_still_counts_per_unit() -> None:
    cp = _base()
    logistics = _setup(cp)
    depot = _site(cp, "ammo", name="Ammo depot")
    update_logistics_from_debriefing(_debrief(logistics, [depot, depot]))
    assert _ammo(logistics, cp) == START_AMMO - 2 * AMMO_LOSS_PER_DEPOT_UNIT


def test_ewr_and_armor_cost_no_ammo() -> None:
    cp = _base()
    logistics = _setup(cp)
    ewr = _site(cp, "ewr", name="EWR")
    armor = _site(cp, "armor", name="Armor")
    update_logistics_from_debriefing(_debrief(logistics, [ewr, armor]))
    assert _ammo(logistics, cp) == START_AMMO


def test_sam_penalty_scales_with_site_size() -> None:
    assert sam_site_ammo_loss(2) == 20  # SA-13 pair
    assert sam_site_ammo_loss(8) == 80  # SA-6 battery
    assert sam_site_ammo_loss(12) == 120  # Hawk
    assert sam_site_ammo_loss(17) == 170  # Patriot
    assert sam_site_ammo_loss(1) == 20  # minimum
    assert sam_site_ammo_loss(40) == 200  # maximum


def test_big_site_costs_more_than_small_site() -> None:
    cp = _base()
    logistics = _setup(cp)
    small = _site(cp, "aa", name="SA-13", size=2)
    big = _site(cp, "aa", name="SA-10", size=16)
    update_logistics_from_debriefing(_debrief(logistics, [small, big]))
    assert _ammo(logistics, cp) == START_AMMO - 20 - 160
