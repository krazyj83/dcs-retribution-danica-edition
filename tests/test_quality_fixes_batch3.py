"""Batch 3 of the 29 Sep quality check: tidy-up."""

from __future__ import annotations

from uuid import uuid4

import pytest

from game.logistics import (
    LogisticsManager,
    LogisticsTransfer,
    TransferStatus,
    WarehouseCategory,
    _weapon_category,
)
from game.settings.settings import (
    BASE_SUPPLIES_SECTION,
    BATTLEFIELD_SECTION,
    CAMPAIGN_MANAGEMENT_PAGE,
    REDFOR_LOGISTICS_SECTION,
    Settings,
)


@pytest.mark.parametrize(
    "name, category",
    [
        ("APU-60-1M with R-60M (AA-8 Aphid-B) - IR AAM", "Air-to-Air"),
        ("R-27ER", "Air-to-Air"),
        ("2 x R-73 (AA-11 Archer)", "Air-to-Air"),
        ("BR-250 - 250kg GP Bomb LD", "Bomb"),
        ("LR-25 - 25 x UnGd Rkts, 50 mm ARF-8/M3 API", "Rocket"),
        ("Kh-29L (AS-14 Kedge) - Semi-Act Laser AGM", "Air-to-Ground Missile"),
    ],
)
def test_weapon_categories(name: str, category: str) -> None:
    assert _weapon_category(name) == category


def test_rack_is_not_air_to_air() -> None:
    assert _weapon_category("TER-9/A: 2 x LAU-131") != "Air-to-Air"


def _transfer(turn: int, status: TransferStatus) -> LogisticsTransfer:
    t = LogisticsTransfer(
        transfer_id=str(uuid4()),
        source_cp_id=uuid4(),
        dest_cp_id=uuid4(),
        dz_id="",
        category=WarehouseCategory.FUEL,
        quantity=10,
        aircraft_type="UH-1H",
        turn_planned=turn,
    )
    t.status = status
    return t


def test_old_finished_transfers_are_dropped() -> None:
    lm = LogisticsManager()
    old_done = _transfer(1, TransferStatus.DELIVERED)
    old_failed = _transfer(2, TransferStatus.FAILED)
    recent = _transfer(8, TransferStatus.DELIVERED)
    waiting = _transfer(1, TransferStatus.PLANNED)
    for t in (old_done, old_failed, recent, waiting):
        lm._transfers[t.transfer_id] = t

    lm.prune_finished_transfers(10)

    assert set(lm._transfers) == {recent.transfer_id, waiting.transfer_id}


def test_fork_settings_have_their_own_sections() -> None:
    def section_of(name: str) -> str:
        for section in Settings.sections(CAMPAIGN_MANAGEMENT_PAGE):
            if name in dict(Settings.fields(CAMPAIGN_MANAGEMENT_PAGE, section)):
                return section
        raise KeyError(name)

    assert section_of("logistics_unlimited_fuel") == BASE_SUPPLIES_SECTION
    assert section_of("logistics_players_load_on_ground") == BASE_SUPPLIES_SECTION
    assert section_of("redfor_logistics") == REDFOR_LOGISTICS_SECTION
    assert section_of("redfor_repairs_air_defences") == REDFOR_LOGISTICS_SECTION
    assert section_of("motorpool_enabled") == BATTLEFIELD_SECTION
    assert section_of("advanced_iads_auto") == BATTLEFIELD_SECTION
