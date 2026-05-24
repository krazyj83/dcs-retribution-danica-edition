from pydantic import BaseModel


class OpenDropZoneDialogRequest(BaseModel):
    lat: float
    lng: float


@router.post(
    "/open-drop-zone-dialog",
    operation_id="open_drop_zone_dialog",
    status_code=status.HTTP_200_OK,
)
def open_drop_zone_dialog(
    body: OpenDropZoneDialogRequest,
    qt: QtCallbacks = Depends(QtContext.get),
) -> None:
    """Open the logistics Drop Zone dialog pre-filled with map coordinates."""
    qt.open_drop_zone_dialog(body.lat, body.lng)
