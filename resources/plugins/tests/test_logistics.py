"""
tests/test_logistics.py

Full test suite for the DCS Retribution logistics module.

Run with:  pytest tests/test_logistics.py -v

Covers:
  - DropZone creation, serialisation, trigger zone naming
  - Warehouse add / consume / reserve / spoilage / rollover
  - Warehouse export_to (inter-base transfer)
  - LogisticsTransfer lifecycle (PLANNED → IN_FLIGHT → DELIVERED/FAILED)
  - LogisticsManager CRUD and turn lifecycle
  - state.json processing (on_state_processed)
  - save/load round-trip (to_dict / from_dict)
"""

from __future__ import annotations

import pytest
from game.logistics import (
    DropZone, DropZoneType,
    Warehouse, WarehouseCategory,
    LogisticsManager, LogisticsTransfer, TransferStatus,
)
from game.logistics.warehouse import WarehouseItem, DEFAULT_CAPACITY


# ======================================================================
# Fixtures
# ======================================================================

@pytest.fixture
def warehouse_blue():
    return Warehouse(cp_id=1, cp_name="Batumi", coalition="blue")

@pytest.fixture
def warehouse_farp():
    return Warehouse(cp_id=2, cp_name="FARP Eagle", coalition="blue", capacity_multiplier=0.3)

@pytest.fixture
def dz_troop():
    return DropZone(
        name="LZ ALPHA",
        dz_type=DropZoneType.TROOP,
        lat=41.6168,
        lon=41.5883,
        cp_id=1,
        coalition="blue",
    )

@pytest.fixture
def dz_cargo():
    return DropZone(
        name="DZ BRAVO",
        dz_type=DropZoneType.CARGO,
        lat=41.7200,
        lon=41.6100,
        cp_id=2,
        coalition="blue",
    )

@pytest.fixture
def manager():
    mgr = LogisticsManager()
    # Set up two warehouses
    mgr.ensure_warehouse(1, "Batumi", "blue")
    mgr.ensure_warehouse(2, "FARP Eagle", "blue", is_farp=True)
    mgr.seed_warehouse(1, WarehouseCategory.FUEL, 1000.0)
    mgr.seed_warehouse(1, WarehouseCategory.TROOPS, 500.0)
    mgr.seed_warehouse(1, WarehouseCategory.AMMUNITION, 3000.0)
    return mgr


# ======================================================================
# DropZone tests
# ======================================================================

class TestDropZone:

    def test_trigger_zone_name_troop(self, dz_troop):
        assert dz_troop.trigger_zone_name == "RETRIBUTION_DZ_TROOP_LZ_ALPHA"

    def test_trigger_zone_name_cargo(self, dz_cargo):
        assert dz_cargo.trigger_zone_name == "RETRIBUTION_DZ_CARGO_DZ_BRAVO"

    def test_trigger_zone_spaces_replaced(self):
        dz = DropZone("drop zone one", DropZoneType.CARGO, 41.0, 41.0, cp_id=1)
        assert " " not in dz.trigger_zone_name
        assert "DROP_ZONE_ONE" in dz.trigger_zone_name

    def test_serialise_roundtrip(self, dz_troop):
        data = dz_troop.to_dict()
        restored = DropZone.from_dict(data)
        assert restored.dz_id    == dz_troop.dz_id
        assert restored.name     == dz_troop.name
        assert restored.dz_type  == dz_troop.dz_type
        assert restored.lat      == pytest.approx(dz_troop.lat)
        assert restored.lon      == pytest.approx(dz_troop.lon)
        assert restored.radius_m == dz_troop.radius_m
        assert restored.active   == dz_troop.active

    def test_uuid_is_unique(self):
        dz1 = DropZone("A", DropZoneType.TROOP, 0, 0, 1)
        dz2 = DropZone("B", DropZoneType.TROOP, 0, 0, 1)
        assert dz1.dz_id != dz2.dz_id


# ======================================================================
# WarehouseItem tests
# ======================================================================

class TestWarehouseItem:

    def test_add_within_capacity(self):
        item = WarehouseItem(WarehouseCategory.FUEL, quantity=0.0, capacity=1000.0)
        surplus = item.add(500.0)
        assert surplus == 0.0
        assert item.quantity == 500.0

    def test_add_exceeds_capacity_returns_surplus(self):
        item = WarehouseItem(WarehouseCategory.FUEL, quantity=900.0, capacity=1000.0)
        surplus = item.add(200.0)
        assert surplus == pytest.approx(100.0)
        assert item.quantity == pytest.approx(1000.0)

    def test_consume_available(self):
        item = WarehouseItem(WarehouseCategory.TROOPS, quantity=300.0, capacity=1000.0)
        consumed = item.consume(100.0)
        assert consumed == pytest.approx(100.0)
        assert item.quantity == pytest.approx(200.0)

    def test_consume_more_than_available(self):
        item = WarehouseItem(WarehouseCategory.TROOPS, quantity=50.0, capacity=1000.0)
        consumed = item.consume(200.0)
        assert consumed == pytest.approx(50.0)
        assert item.quantity == pytest.approx(0.0)

    def test_reserve_reduces_available(self):
        item = WarehouseItem(WarehouseCategory.AMMUNITION, quantity=500.0, capacity=5000.0)
        reserved = item.reserve(200.0)
        assert reserved == pytest.approx(200.0)
        assert item.available == pytest.approx(300.0)
        assert item.quantity  == pytest.approx(500.0)

    def test_consume_respects_reserve(self):
        item = WarehouseItem(WarehouseCategory.AMMUNITION, quantity=500.0, capacity=5000.0)
        item.reserve(300.0)
        consumed = item.consume(400.0)  # Only 200 available
        assert consumed == pytest.approx(200.0)

    def test_spoilage_fuel(self):
        item = WarehouseItem(WarehouseCategory.FUEL, quantity=1000.0, capacity=2000.0)
        lost = item.apply_spoilage()
        # FUEL spoilage rate is 0.02
        assert lost == pytest.approx(20.0, rel=0.01)
        assert item.quantity == pytest.approx(980.0, rel=0.01)

    def test_spoilage_troops_none(self):
        item = WarehouseItem(WarehouseCategory.TROOPS, quantity=500.0, capacity=1000.0)
        lost = item.apply_spoilage()
        assert lost == 0.0
        assert item.quantity == 500.0

    def test_serialise_roundtrip(self):
        item = WarehouseItem(WarehouseCategory.SPARE_PARTS, quantity=123.4, capacity=500.0, reserved=50.0)
        data = item.to_dict()
        restored = WarehouseItem.from_dict(data)
        assert restored.category == item.category
        assert restored.quantity == pytest.approx(item.quantity, rel=0.01)
        assert restored.reserved == pytest.approx(item.reserved, rel=0.01)


# ======================================================================
# Warehouse tests
# ======================================================================

class TestWarehouse:

    def test_initial_stock_is_zero(self, warehouse_blue):
        assert warehouse_blue.quantity(WarehouseCategory.FUEL) == 0.0

    def test_add_and_retrieve(self, warehouse_blue):
        surplus = warehouse_blue.add(WarehouseCategory.FUEL, 500.0)
        assert surplus == 0.0
        assert warehouse_blue.quantity(WarehouseCategory.FUEL) == pytest.approx(500.0)

    def test_is_critical_below_threshold(self, warehouse_blue):
        # Add 5% of capacity → critical
        cap = DEFAULT_CAPACITY[WarehouseCategory.FUEL]
        warehouse_blue.add(WarehouseCategory.FUEL, cap * 0.05)
        assert warehouse_blue.is_critical(WarehouseCategory.FUEL) is True

    def test_is_not_critical_above_threshold(self, warehouse_blue):
        cap = DEFAULT_CAPACITY[WarehouseCategory.FUEL]
        warehouse_blue.add(WarehouseCategory.FUEL, cap * 0.5)
        assert warehouse_blue.is_critical(WarehouseCategory.FUEL) is False

    def test_farp_smaller_capacity(self, warehouse_farp):
        farp_cap = warehouse_farp.stock[WarehouseCategory.FUEL].capacity
        std_cap  = DEFAULT_CAPACITY[WarehouseCategory.FUEL]
        assert farp_cap == pytest.approx(std_cap * 0.3, rel=0.01)

    def test_export_to_transfers_stock(self, warehouse_blue):
        dest = Warehouse(cp_id=99, cp_name="Dest", coalition="blue")
        warehouse_blue.add(WarehouseCategory.FUEL, 800.0)
        transferred = warehouse_blue.export_to(dest, WarehouseCategory.FUEL, 300.0)
        assert transferred == pytest.approx(300.0)
        assert warehouse_blue.quantity(WarehouseCategory.FUEL) == pytest.approx(500.0)
        assert dest.quantity(WarehouseCategory.FUEL) == pytest.approx(300.0)

    def test_export_to_capped_by_dest_capacity(self, warehouse_blue, warehouse_farp):
        """Surplus is returned to source if destination is full."""
        farp_cap = warehouse_farp.stock[WarehouseCategory.FUEL].capacity
        warehouse_blue.add(WarehouseCategory.FUEL, 1500.0)
        # Fill FARP to near capacity
        warehouse_farp.add(WarehouseCategory.FUEL, farp_cap - 50.0)
        # Try to send 200 → only 50 fits
        transferred = warehouse_blue.export_to(warehouse_farp, WarehouseCategory.FUEL, 200.0)
        assert transferred == pytest.approx(50.0, abs=1.0)

    def test_rollover_carries_stock(self, warehouse_blue):
        warehouse_blue.add(WarehouseCategory.TROOPS, 400.0)
        snapshot = warehouse_blue.to_dict()
        new_wh = Warehouse(cp_id=1, cp_name="Batumi", coalition="blue")
        new_wh.rollover(snapshot)
        # After rollover + spoilage (troops have 0% spoilage), stock should be same
        assert new_wh.quantity(WarehouseCategory.TROOPS) == pytest.approx(400.0)

    def test_rollover_clears_reservations(self, warehouse_blue):
        warehouse_blue.add(WarehouseCategory.AMMUNITION, 1000.0)
        warehouse_blue.reserve(WarehouseCategory.AMMUNITION, 300.0)
        snapshot = warehouse_blue.to_dict()
        new_wh = Warehouse(cp_id=1, cp_name="Batumi", coalition="blue")
        new_wh.rollover(snapshot)
        # Reservations don't carry over
        assert new_wh.stock[WarehouseCategory.AMMUNITION].reserved == 0.0

    def test_serialise_roundtrip(self, warehouse_blue):
        warehouse_blue.add(WarehouseCategory.FUEL, 750.0)
        warehouse_blue.add(WarehouseCategory.TROOPS, 200.0)
        data = warehouse_blue.to_dict()
        restored = Warehouse.from_dict(data)
        assert restored.cp_id   == warehouse_blue.cp_id
        assert restored.cp_name == warehouse_blue.cp_name
        assert restored.quantity(WarehouseCategory.FUEL) == pytest.approx(750.0)


# ======================================================================
# LogisticsTransfer tests
# ======================================================================

class TestLogisticsTransfer:

    def test_initial_status_planned(self):
        t = LogisticsTransfer(
            source_cp_id=1, dest_cp_id=2, dz_id="abc",
            category=WarehouseCategory.FUEL, quantity=200.0,
        )
        assert t.status == TransferStatus.PLANNED
        assert t.is_active is True

    def test_mark_in_flight(self):
        t = LogisticsTransfer(1, 2, "abc", WarehouseCategory.FUEL, 200.0)
        t.mark_in_flight()
        assert t.status == TransferStatus.IN_FLIGHT

    def test_cannot_mark_in_flight_twice(self):
        t = LogisticsTransfer(1, 2, "abc", WarehouseCategory.FUEL, 200.0)
        t.mark_in_flight()
        with pytest.raises(ValueError):
            t.mark_in_flight()

    def test_mark_delivered(self):
        t = LogisticsTransfer(1, 2, "abc", WarehouseCategory.FUEL, 200.0)
        t.mark_in_flight()
        t.mark_delivered(180.0, turn=5)
        assert t.status     == TransferStatus.DELIVERED
        assert t.delivered  == pytest.approx(180.0)
        assert t.turn_resolved == 5
        assert t.is_active is False

    def test_success_rate(self):
        t = LogisticsTransfer(1, 2, "abc", WarehouseCategory.FUEL, 200.0)
        t.mark_in_flight()
        t.mark_delivered(150.0, 3)
        assert t.success_rate == pytest.approx(0.75)

    def test_mark_failed(self):
        t = LogisticsTransfer(1, 2, "abc", WarehouseCategory.FUEL, 200.0)
        t.mark_in_flight()
        t.mark_failed(turn=4)
        assert t.status    == TransferStatus.FAILED
        assert t.delivered == 0.0
        assert t.is_active is False

    def test_serialise_roundtrip(self):
        t = LogisticsTransfer(
            source_cp_id=1, dest_cp_id=2, dz_id="xyz",
            category=WarehouseCategory.TROOPS, quantity=300.0,
            aircraft_type="CH-47D", notes="test delivery", turn_planned=3,
        )
        data = t.to_dict()
        restored = LogisticsTransfer.from_dict(data)
        assert restored.transfer_id  == t.transfer_id
        assert restored.category     == t.category
        assert restored.quantity     == t.quantity
        assert restored.aircraft_type == t.aircraft_type


# ======================================================================
# LogisticsManager tests
# ======================================================================

class TestLogisticsManager:

    def test_add_and_retrieve_drop_zone(self, manager, dz_troop):
        manager.add_drop_zone(dz_troop)
        retrieved = manager.get_drop_zone(dz_troop.dz_id)
        assert retrieved.name == "LZ ALPHA"

    def test_remove_drop_zone(self, manager, dz_troop):
        manager.add_drop_zone(dz_troop)
        result = manager.remove_drop_zone(dz_troop.dz_id)
        assert result is True
        assert manager.get_drop_zone(dz_troop.dz_id) is None

    def test_remove_unknown_zone_returns_false(self, manager):
        assert manager.remove_drop_zone("nonexistent") is False

    def test_schedule_transfer_succeeds(self, manager, dz_cargo):
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.FUEL,
            quantity=200.0,
        )
        assert transfer is not None
        assert transfer.status == TransferStatus.PLANNED
        # Stock should be reserved
        src_wh = manager.get_warehouse(1)
        assert src_wh.available(WarehouseCategory.FUEL) == pytest.approx(800.0)

    def test_schedule_transfer_fails_no_stock(self, manager, dz_cargo):
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.FUEL,
            quantity=99999.0,   # far more than available
        )
        assert transfer is None

    def test_cancel_transfer_releases_reservation(self, manager, dz_cargo):
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.FUEL,
            quantity=200.0,
        )
        available_before = manager.get_warehouse(1).available(WarehouseCategory.FUEL)
        manager.cancel_transfer(transfer.transfer_id)
        available_after  = manager.get_warehouse(1).available(WarehouseCategory.FUEL)
        assert available_after > available_before

    def test_on_turn_end_moves_to_in_flight(self, manager, dz_cargo):
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.FUEL,
            quantity=100.0,
        )
        manager.on_turn_end(current_turn=1)
        assert transfer.status == TransferStatus.IN_FLIGHT

    def test_on_state_processed_delivers(self, manager, dz_cargo):
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.FUEL,
            quantity=100.0,
        )
        manager.on_turn_end(1)
        state = {
            "logistics_events": [
                {
                    "transfer_id": transfer.transfer_id,
                    "delivered":   95.0,
                    "success":     True,
                }
            ]
        }
        manager.on_state_processed(state, current_turn=1)
        assert transfer.status == TransferStatus.DELIVERED
        assert transfer.delivered == pytest.approx(95.0)
        # Destination warehouse received the stock
        dst_wh = manager.get_warehouse(2)
        assert dst_wh.quantity(WarehouseCategory.FUEL) == pytest.approx(95.0)

    def test_on_state_processed_fails_missing_event(self, manager, dz_cargo):
        """Transfer not in state events → auto-failed."""
        manager.add_drop_zone(dz_cargo)
        transfer = manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.TROOPS,
            quantity=50.0,
        )
        manager.on_turn_end(1)
        # Empty state — no events
        manager.on_state_processed({}, current_turn=1)
        assert transfer.status == TransferStatus.FAILED

    def test_full_serialise_roundtrip(self, manager, dz_troop, dz_cargo):
        manager.add_drop_zone(dz_troop)
        manager.add_drop_zone(dz_cargo)
        manager.schedule_transfer(
            source_cp_id=1, dest_cp_id=2,
            dz_id=dz_cargo.dz_id,
            category=WarehouseCategory.AMMUNITION,
            quantity=500.0,
        )
        data = manager.to_dict()
        restored = LogisticsManager.from_dict(data)
        assert len(restored.all_drop_zones) == 2
        assert restored.get_warehouse(1) is not None
        assert restored.get_warehouse(2) is not None
        transfers = list(restored.active_transfers)
        assert len(transfers) == 1
        assert transfers[0].category == WarehouseCategory.AMMUNITION
