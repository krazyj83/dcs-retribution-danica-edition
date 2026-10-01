"""Campaign tab data (logistics/campaign_stats.py), the debrief summary and
the supply-changed map event."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from game.logistics import (
    LogisticsManager,
    LogisticsTransfer,
    TransferStatus,
    WarehouseCategory,
    WeaponInventory,
    new_base_warehouse,
)
from game.logistics.campaign_stats import (
    StatsRecorder,
    blue_capacity,
    blue_stock_history,
    blue_stock_now,
    turn_stats,
)
from game.logistics.debrief_hook import MAX_DEBRIEF_HIGHLIGHTS, debrief_highlights
from game.logistics.history import record_turn
from game.sim.gameupdateevents import GameUpdateEvents
from game.theater.player import Player

FUEL, AMMO = WarehouseCategory.FUEL, WarehouseCategory.AMMUNITION


def _logistics() -> Any:
    lm = LogisticsManager()
    blue = new_base_warehouse(
        SimpleNamespace(id=uuid4(), name="Kutaisi", captured=Player.BLUE)
    )
    red = new_base_warehouse(
        SimpleNamespace(id=uuid4(), name="Sochi", captured=Player.RED)
    )
    lm.add_warehouse(blue)
    lm.add_warehouse(red)
    inv = WeaponInventory(cp_id=blue.cp_id, cp_name=blue.cp_name)
    inv.add_item("{AIM120C}", "AIM-120C", "Air-to-Air", quantity=40)
    lm.set_weapon_inventory(inv)
    return lm, blue, red


def test_recorder_measures_each_step() -> None:
    lm, blue, red = _logistics()
    rec = StatsRecorder(lm, 3)

    def fly() -> list[str]:
        blue.stock[FUEL].quantity -= 120
        red.stock[FUEL].quantity -= 500  # REDFOR use doesn't count
        return ["flown"]

    assert rec.measure("fuel", fly) == ["flown"]
    rec.measure(
        "weapons",
        lambda: lm.get_weapon_inventory(blue.cp_id)
        .items["{AIM120C}"]
        .__setattr__("quantity", 34),
    )
    rec.measure(
        "damage",
        lambda: blue.stock[AMMO].__setattr__(
            "quantity", blue.stock[AMMO].quantity - 75
        ),
    )

    t = LogisticsTransfer(
        transfer_id="t1",
        source_cp_id=blue.cp_id,
        dest_cp_id=blue.cp_id,
        dz_id="",
        category=FUEL,
        quantity=10,
        aircraft_type="UH-1H",
        turn_planned=3,
        status=TransferStatus.IN_FLIGHT,
    )
    lm._transfers[t.transfer_id] = t
    rec.start("transfers")
    t.status = TransferStatus.FAILED
    rec.stop("transfers")
    rec.save()

    (stats,) = turn_stats(lm)
    assert stats.turn == 3
    assert stats.fuel_used == 120
    assert stats.weapons_used == 6
    assert stats.stock_lost == 75
    assert (stats.transfers_delivered, stats.transfers_lost) == (0, 1)


def test_a_regenerated_turn_replaces_its_numbers() -> None:
    lm, _, _ = _logistics()
    StatsRecorder(lm, 2).save()
    rec = StatsRecorder(lm, 2)
    rec.stats.fuel_used = 50
    rec.save()
    assert [s.fuel_used for s in turn_stats(lm)] == [50]


def test_stock_history_adds_up_blue_bases_only() -> None:
    lm, blue, red = _logistics()
    record_turn(lm, 1)
    blue.stock[FUEL].quantity -= 300
    record_turn(lm, 2)

    points = blue_stock_history(lm)
    assert [p.turn for p in points] == [1, 2]
    assert points[0].fuel - points[1].fuel == 300
    assert points[0].fuel == blue.stock[FUEL].capacity  # red's fuel not added
    now = blue_stock_now(lm, 3)
    assert now is not None and now.weapons == 40
    assert blue_capacity(lm) == blue.stock[FUEL].capacity


def test_debrief_shows_only_the_important_lines() -> None:
    lines = [
        "Kutaisi: 4 sortie(s) used 60 fuel, 900 left",
        "Transfer 1a2b: flight lost, 250 fuel lost",
        "Senaki: 2 sortie(s) used 30 fuel — OUT OF FUEL",
        "Recon over Sochi: fuel Good (~90%)",
    ]
    assert debrief_highlights(lines) == [lines[1], lines[2]]
    many = [f"Base {i}: captured by REDFOR" for i in range(9)]
    assert len(debrief_highlights(many)) == MAX_DEBRIEF_HIGHLIGHTS


def test_supply_changed_event_reaches_the_map() -> None:
    from game.server.eventstream.models import GameUpdateEventsJs

    events = GameUpdateEvents().update_supply_status()
    assert not events.empty
    js = GameUpdateEventsJs.from_events(events, None)
    assert js.supply_status_changed is True
