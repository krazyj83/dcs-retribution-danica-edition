"""
game/server/routes/logistics.py

FastAPI routes for the Logistics module.
Mounted at /api/v1/logistics by the main server app.

These endpoints are used by:
  - The web UI (TypeScript client)
  - The Qt panel (via the existing internal HTTP client)
  - Any external tools / co-op clients

All routes use Pydantic models for request/response validation,
which means FastAPI auto-generates an OpenAPI schema for them
at /docs — no hand-written documentation needed.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from game.logistics import (
    DropZone, DropZoneType, WarehouseCategory, LogisticsTransfer,
)

router = APIRouter(prefix="/api/v1/logistics", tags=["logistics"])


# ======================================================================
# Pydantic request / response models
# ======================================================================

class DropZoneCreate(BaseModel):
    name:      str         = Field(..., min_length=1, max_length=64)
    dz_type:   DropZoneType
    lat:       float       = Field(..., ge=-90.0, le=90.0)
    lon:       float       = Field(..., ge=-180.0, le=180.0)
    radius_m:  float       = Field(500.0, ge=100.0, le=5000.0)
    cp_id:     int
    coalition: str         = Field("blue", pattern="^(blue|red)$")
    active:    bool        = True
    notes:     str         = ""


class DropZoneResponse(BaseModel):
    dz_id:             str
    name:              str
    dz_type:           str
    lat:               float
    lon:               float
    radius_m:          float
    cp_id:             int
    coalition:         str
    active:            bool
    notes:             str
    trigger_zone_name: str


class WarehouseItemResponse(BaseModel):
    category: str
    quantity: float
    capacity: float
    reserved: float
    available: float
    pct_full: float


class WarehouseResponse(BaseModel):
    cp_id:     int
    cp_name:   str
    coalition: str
    stock:     List[WarehouseItemResponse]
    critical_categories: List[str]


class TransferCreate(BaseModel):
    source_cp_id:  int
    dest_cp_id:    int
    dz_id:         str
    category:      WarehouseCategory
    quantity:      float = Field(..., gt=0)
    aircraft_type: str   = "UH-1H"
    notes:         str   = ""


class TransferResponse(BaseModel):
    transfer_id:   str
    source_cp_id:  int
    dest_cp_id:    int
    dz_id:         str
    category:      str
    quantity:      float
    delivered:     float
    status:        str
    aircraft_type: str
    turn_planned:  int
    turn_resolved: Optional[int]
    notes:         str


class ExportRequest(BaseModel):
    source_cp_id: int
    dest_cp_id:   int
    category:     WarehouseCategory
    amount:       float = Field(..., gt=0)


class ExportResponse(BaseModel):
    transferred: float
    source_remaining: float
    dest_new_total:   float


# ======================================================================
# Dependency — get the logistics manager from the running game
# ======================================================================

def get_logistics(request):
    """
    FastAPI dependency. Retrieves the LogisticsManager from the
    running game instance attached to the app state.

    Usage: logistics: LogisticsManager = Depends(get_logistics)
    """
    game = request.app.state.game
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No campaign loaded",
        )
    return game.logistics


# ======================================================================
# Drop Zone endpoints
# ======================================================================

@router.get("/dropzones", response_model=List[DropZoneResponse])
async def list_drop_zones(
    coalition: Optional[str] = None,
    active_only: bool = False,
    logistics=Depends(get_logistics),
):
    """
    List all drop zones, optionally filtered by coalition and active state.
    """
    dzs = logistics.all_drop_zones
    if coalition:
        dzs = [dz for dz in dzs if dz.coalition == coalition]
    if active_only:
        dzs = [dz for dz in dzs if dz.active]
    return [
        DropZoneResponse(
            dz_id=dz.dz_id,
            name=dz.name,
            dz_type=dz.dz_type.value,
            lat=dz.lat,
            lon=dz.lon,
            radius_m=dz.radius_m,
            cp_id=dz.cp_id,
            coalition=dz.coalition,
            active=dz.active,
            notes=dz.notes,
            trigger_zone_name=dz.trigger_zone_name,
        )
        for dz in dzs
    ]


@router.post("/dropzones", response_model=DropZoneResponse, status_code=201)
async def create_drop_zone(
    body: DropZoneCreate,
    logistics=Depends(get_logistics),
):
    """
    Create a new drop zone. The zone will appear in the next generated mission.
    """
    dz = DropZone(
        name=body.name.upper(),
        dz_type=body.dz_type,
        lat=body.lat,
        lon=body.lon,
        radius_m=body.radius_m,
        cp_id=body.cp_id,
        coalition=body.coalition,
        active=body.active,
        notes=body.notes,
    )
    logistics.add_drop_zone(dz)
    return DropZoneResponse(
        dz_id=dz.dz_id, name=dz.name, dz_type=dz.dz_type.value,
        lat=dz.lat, lon=dz.lon, radius_m=dz.radius_m, cp_id=dz.cp_id,
        coalition=dz.coalition, active=dz.active, notes=dz.notes,
        trigger_zone_name=dz.trigger_zone_name,
    )


@router.delete("/dropzones/{dz_id}", status_code=204)
async def delete_drop_zone(dz_id: str, logistics=Depends(get_logistics)):
    """Delete a drop zone. Cancels any planned transfers targeting it."""
    if not logistics.remove_drop_zone(dz_id):
        raise HTTPException(status_code=404, detail="Drop zone not found")


@router.patch("/dropzones/{dz_id}/toggle", response_model=DropZoneResponse)
async def toggle_drop_zone(dz_id: str, logistics=Depends(get_logistics)):
    """Toggle a drop zone's active state."""
    dz = logistics.get_drop_zone(dz_id)
    if not dz:
        raise HTTPException(status_code=404, detail="Drop zone not found")
    dz.active = not dz.active
    return DropZoneResponse(
        dz_id=dz.dz_id, name=dz.name, dz_type=dz.dz_type.value,
        lat=dz.lat, lon=dz.lon, radius_m=dz.radius_m, cp_id=dz.cp_id,
        coalition=dz.coalition, active=dz.active, notes=dz.notes,
        trigger_zone_name=dz.trigger_zone_name,
    )


# ======================================================================
# Warehouse endpoints
# ======================================================================

@router.get("/warehouses", response_model=List[WarehouseResponse])
async def list_warehouses(
    coalition: Optional[str] = None,
    logistics=Depends(get_logistics),
):
    """List all warehouses with current stock levels."""
    warehouses = (
        logistics.warehouses_for_coalition(coalition)
        if coalition
        else list(logistics._warehouses.values())
    )
    result = []
    for wh in warehouses:
        stock_list = []
        critical = []
        for cat, item in wh.stock.items():
            pct = round(item.quantity / item.capacity * 100, 1) if item.capacity else 0.0
            stock_list.append(WarehouseItemResponse(
                category=cat.value,
                quantity=item.quantity,
                capacity=item.capacity,
                reserved=item.reserved,
                available=item.available,
                pct_full=pct,
            ))
            if wh.is_critical(cat):
                critical.append(cat.value)
        result.append(WarehouseResponse(
            cp_id=wh.cp_id,
            cp_name=wh.cp_name,
            coalition=wh.coalition,
            stock=stock_list,
            critical_categories=critical,
        ))
    return result


@router.post("/warehouses/export", response_model=ExportResponse)
async def export_stock(body: ExportRequest, logistics=Depends(get_logistics)):
    """
    Directly transfer stock between two warehouses (immediate, no flight needed).
    Useful for balancing stock before mission generation.
    """
    src = logistics.get_warehouse(body.source_cp_id)
    dst = logistics.get_warehouse(body.dest_cp_id)
    if not src:
        raise HTTPException(status_code=404, detail=f"Source warehouse {body.source_cp_id} not found")
    if not dst:
        raise HTTPException(status_code=404, detail=f"Destination warehouse {body.dest_cp_id} not found")
    if body.source_cp_id == body.dest_cp_id:
        raise HTTPException(status_code=400, detail="Source and destination must differ")

    transferred = src.export_to(dst, body.category, body.amount)
    return ExportResponse(
        transferred=transferred,
        source_remaining=src.quantity(body.category),
        dest_new_total=dst.quantity(body.category),
    )


# ======================================================================
# Transfer endpoints
# ======================================================================

@router.get("/transfers", response_model=List[TransferResponse])
async def list_transfers(
    status_filter: Optional[str] = None,
    logistics=Depends(get_logistics),
):
    """List all logistics transfers, optionally filtered by status."""
    transfers = list(logistics._transfers.values())
    if status_filter:
        transfers = [t for t in transfers if t.status.value == status_filter]
    return [_transfer_response(t) for t in transfers]


@router.post("/transfers", response_model=TransferResponse, status_code=201)
async def schedule_transfer(
    body: TransferCreate,
    logistics=Depends(get_logistics),
):
    """
    Schedule a logistics transfer. Reserves stock at source immediately.
    The transfer becomes a helicopter/transport flight in the next mission.
    """
    game = None  # In production: get current turn from game object
    transfer = logistics.schedule_transfer(
        source_cp_id=body.source_cp_id,
        dest_cp_id=body.dest_cp_id,
        dz_id=body.dz_id,
        category=body.category,
        quantity=body.quantity,
        aircraft_type=body.aircraft_type,
        turn=0,
        notes=body.notes,
    )
    if transfer is None:
        raise HTTPException(
            status_code=409,
            detail="Insufficient available stock at source warehouse",
        )
    return _transfer_response(transfer)


@router.delete("/transfers/{transfer_id}", status_code=204)
async def cancel_transfer(transfer_id: str, logistics=Depends(get_logistics)):
    """Cancel a PLANNED transfer and release the stock reservation."""
    if not logistics.cancel_transfer(transfer_id):
        raise HTTPException(
            status_code=404,
            detail="Transfer not found or not in PLANNED state",
        )


def _transfer_response(t: LogisticsTransfer) -> TransferResponse:
    return TransferResponse(
        transfer_id=t.transfer_id,
        source_cp_id=t.source_cp_id,
        dest_cp_id=t.dest_cp_id,
        dz_id=t.dz_id,
        category=t.category.value,
        quantity=t.quantity,
        delivered=t.delivered,
        status=t.status.value,
        aircraft_type=t.aircraft_type,
        turn_planned=t.turn_planned,
        turn_resolved=t.turn_resolved,
        notes=t.notes,
    )
