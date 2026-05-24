from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from game.server.leaflet import LeafletPoint


class ConvoyRouteJs(BaseModel):
    """A player-drawn convoy route on the campaign map."""

    id: UUID
    name: str
    start: LeafletPoint
    end: LeafletPoint

    class Config:
        title = "ConvoyRoute"


class CreateConvoyRouteRequest(BaseModel):
    name: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
