from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel
from game.server.leaflet import LeafletPoint


class DropZoneJs(BaseModel):
    """A player-placed drop zone on the campaign map."""

    id: UUID
    name: str
    position: LeafletPoint
    #: The friendly base the zone belongs to ("" if none).
    base: str = ""
    #: The zone's forward cache, one line per weapon ("8x AGM-114K Hellfire").
    cache: list[str] = []

    class Config:
        title = "DropZone"


class CreateDropZoneRequest(BaseModel):
    name: str
    lat: float
    lng: float
