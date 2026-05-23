/**
 * DropZoneLayer.tsx
 *
 * Two responsibilities:
 *
 *  1. RIGHT-CLICK anywhere on the map  →  small popup asking for a DZ name
 *     →  confirm  →  POST to /drop-zones/  →  marker appears.
 *
 *  2. CLICK a DZ marker  →  popup with:
 *       • "Create Mission"  →  POST to /qt/create-package/drop-zone/{id}
 *                              This opens the standard Retribution New Package
 *                              dialog (AIR_ASSAULT / TRANSPORT / LOGISTIC).
 *       • "Remove"          →  DELETE /drop-zones/{id}
 *
 * No in-game Lua, no F10 menu, no mission generator changes needed.
 */

import { LatLng } from "leaflet";
import { useState } from "react";
import { CircleMarker, Popup, useMapEvents } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import {
  DropZone,
  createDropZone,
  deleteDropZone,
  selectDropZones,
  serverBase,
} from "../../api/dropZonesSlice";

// ── Right-click → create DZ ───────────────────────────────────────────────────

function MapRightClickHandler() {
  const dispatch = useAppDispatch();
  const [pending, setPending] = useState<{ latlng: LatLng; name: string } | null>(null);

  useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      setPending({ latlng: e.latlng, name: "" });
    },
    // Dismiss if the user left-clicks elsewhere
    click() {
      setPending(null);
    },
  });

  if (!pending) return null;

  const confirm = () => {
    dispatch(
      createDropZone({
        name: pending.name.trim() || "Drop Zone",
        lat: pending.latlng.lat,
        lng: pending.latlng.lng,
      })
    );
    setPending(null);
  };

  return (
    <Popup position={pending.latlng} eventHandlers={{ remove: () => setPending(null) }}>
      <div style={popupWrap}>
        <strong style={{ fontSize: 13 }}>New Drop Zone</strong>
        <input
          autoFocus
          style={inputStyle}
          placeholder="Name (e.g. DZ Alpha)"
          value={pending.name}
          onChange={(e) => setPending({ ...pending, name: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && confirm()}
        />
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button style={btn} onClick={confirm}>
            ✔ Create
          </button>
          <button style={{ ...btn, background: "#555" }} onClick={() => setPending(null)}>
            Cancel
          </button>
        </div>
      </div>
    </Popup>
  );
}

// ── DZ markers ────────────────────────────────────────────────────────────────

function DropZoneMarkers() {
  const dispatch = useAppDispatch();
  const zones = useAppSelector(selectDropZones);

  const openPackageDialog = async (dz: DropZone) => {
    // Fire-and-forget: Python side opens the Retribution New Package dialog.
    await fetch(`${serverBase()}/qt/create-package/drop-zone/${dz.id}`, {
      method: "POST",
    });
  };

  return (
    <>
      {zones.map((dz) => (
        <CircleMarker
          key={dz.id}
          center={[dz.position.lat, dz.position.lng]}
          radius={11}
          pathOptions={{
            color: "#f5a623",
            weight: 2,
            fillColor: "#f5a623",
            fillOpacity: 0.3,
          }}
        >
          <Popup>
            <div style={popupWrap}>
              <strong style={{ fontSize: 13 }}>🎯 {dz.name}</strong>
              <div style={{ fontSize: 11, color: "#999", margin: "2px 0 8px" }}>
                {dz.position.lat.toFixed(4)}, {dz.position.lng.toFixed(4)}
              </div>
              <button
                style={{ ...btn, width: "100%", marginBottom: 5 }}
                onClick={() => openPackageDialog(dz)}
              >
                📋 Create Mission
              </button>
              <button
                style={{ ...btn, width: "100%", background: "#7b241c" }}
                onClick={() => dispatch(deleteDropZone(dz.id))}
              >
                🗑 Remove Drop Zone
              </button>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const popupWrap: React.CSSProperties = { minWidth: 190 };

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 8,
  background: "#1a252f",
  color: "#ecf0f1",
  border: "1px solid #555",
  borderRadius: 3,
  padding: "5px 7px",
  fontSize: 12,
  boxSizing: "border-box",
};

const btn: React.CSSProperties = {
  background: "#2c3e50",
  color: "#ecf0f1",
  border: "1px solid #555",
  borderRadius: 4,
  padding: "5px 10px",
  cursor: "pointer",
  fontSize: 12,
};

// ── Export ────────────────────────────────────────────────────────────────────

/**
 * Add inside <MapContainer> as a LayersControl.Overlay.
 * Handles both right-click creation and marker display.
 */
export default function DropZoneLayer() {
  return (
    <>
      <DropZoneMarkers />
      <MapRightClickHandler />
    </>
  );
}
