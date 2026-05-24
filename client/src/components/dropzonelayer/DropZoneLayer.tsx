content = """import { LatLng } from "leaflet";
import React, { useState } from "react";
import { CircleMarker, Polyline, Popup, Tooltip, useMapEvents } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { DropZone, deleteDropZone, selectDropZones, serverBase } from "../../api/dropZonesSlice";
import { createConvoyRoute, deleteConvoyRoute, selectConvoyRoutes } from "../../api/convoyRoutesSlice";
import type { ConvoyRoute } from "../../api/convoyRoutesSlice";

const popupWrap: React.CSSProperties = { minWidth: 210 };
const menuWrap: React.CSSProperties = { minWidth: 200, padding: "4px 0" };
const menuItem: React.CSSProperties = { display: "block", width: "100%", background: "transparent", color: "#ecf0f1", border: "none", borderRadius: 0, padding: "8px 14px", cursor: "pointer", fontSize: 13, textAlign: "left" };
const menuDivider: React.CSSProperties = { borderTop: "1px solid #444", margin: "4px 0" };
const inputStyle: React.CSSProperties = { display: "block", width: "100%", marginTop: 8, background: "#1a252f", color: "#ecf0f1", border: "1px solid #555", borderRadius: 3, padding: "5px 7px", fontSize: 12, boxSizing: "border-box" };
const btn: React.CSSProperties = { background: "#2c3e50", color: "#ecf0f1", border: "1px solid #555", borderRadius: 4, padding: "5px 10px", cursor: "pointer", fontSize: 12 };
const dangerBtn: React.CSSProperties = { ...btn, background: "#7b241c" };
const ROUTE_COLOR = "#f5a623";
const PENDING_COLOR = "#ffffff";

type MenuState = { latlng: LatLng };
type RouteState =
  | { step: "start"; latlng: LatLng }
  | { step: "end"; start: LatLng; end: LatLng; name: string };

function MapRightClickHandler() {
  const dispatch = useAppDispatch();
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [route, setRoute] = useState<RouteState | null>(null);

  useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      if (route?.step === "start") {
        setRoute({ step: "end", start: route.latlng, end: e.latlng, name: "" });
        return;
      }
      setMenu({ latlng: e.latlng });
    },
    click() {
      if (route?.step === "start") setRoute(null);
      setMenu(null);
    },
  });

  if (menu && !route) {
    const onAddDropZone = async () => {
      setMenu(null);
      await fetch(`${serverBase()}/qt/open-drop-zone-dialog`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: menu.latlng.lat, lng: menu.latlng.lng }),
      });
    };
    const onAddConvoyRoute = () => {
      setRoute({ step: "start", latlng: menu.latlng });
      setMenu(null);
    };
    return (
      <Popup position={menu.latlng} eventHandlers={{ remove: () => setMenu(null) }} closeButton={false}>
        <div style={menuWrap}>
          <button style={menuItem} onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")} onClick={onAddDropZone}>
            🎯 Add Drop Zone
          </button>
          <div style={menuDivider} />
          <button style={menuItem} onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")} onClick={onAddConvoyRoute}>
            🚛 Add Convoy Route
          </button>
        </div>
      </Popup>
    );
  }

  if (route?.step === "start") {
    return (
      <CircleMarker center={route.latlng} radius={8} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
        <Tooltip permanent direction="top" offset={[0, -12]}>Route start — right-click to set end point</Tooltip>
      </CircleMarker>
    );
  }

  if (route?.step === "end") {
    const confirm = () => {
      dispatch(createConvoyRoute({ name: route.name.trim() || "Convoy Route", start_lat: route.start.lat, start_lng: route.start.lng, end_lat: route.end.lat, end_lng: route.end.lng }));
      setRoute(null);
    };
    return (
      <>
        <Polyline positions={[route.start, route.end]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }} />
        <CircleMarker center={route.start} radius={6} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
        <Popup position={route.end} eventHandlers={{ remove: () => setRoute(null) }}>
          <div style={popupWrap}>
            <strong style={{ fontSize: 13 }}>🚛 New Convoy Route</strong>
            <input autoFocus style={inputStyle} placeholder="Route name (e.g. MSR Alpha)" value={route.name} onChange={(e) => setRoute({ ...route, name: e.target.value })} onKeyDown={(e) => e.key === "Enter" && confirm()} />
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button style={btn} onClick={confirm}>✔ Create</button>
              <button style={{ ...btn, background: "#555" }} onClick={() => setRoute(null)}>Cancel</button>
            </div>
          </div>
        </Popup>
      </>
    );
  }

  return null;
}

function DropZoneMarkers() {
  const dispatch = useAppDispatch();
  const zones = useAppSelector(selectDropZones);
  const openPackageDialog = async (dz: DropZone) => {
    await fetch(`${serverBase()}/qt/create-package/drop-zone/${dz.id}`, { method: "POST" });
  };
  return (
    <>
      {zones.map((dz) => (
        <CircleMarker key={dz.id} center={[dz.position.lat, dz.position.lng]} radius={11} pathOptions={{ color: "#f5a623", weight: 2, fillColor: "#f5a623", fillOpacity: 0.3 }}>
          <Popup>
            <div style={popupWrap}>
              <strong style={{ fontSize: 13 }}>🎯 {dz.name}</strong>
              <div style={{ fontSize: 11, color: "#999", margin: "2px 0 8px" }}>{dz.position.lat.toFixed(4)}, {dz.position.lng.toFixed(4)}</div>
              <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={() => openPackageDialog(dz)}>📋 Create Mission</button>
              <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteDropZone(dz.id))}>🗑 Remove Drop Zone</button>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
}

function ConvoyRouteMarkers() {
  const dispatch = useAppDispatch();
  const routes = useAppSelector(selectConvoyRoutes);
  const openEscortDialog = async (route: ConvoyRoute) => {
    await fetch(`${serverBase()}/qt/create-package/convoy-route/${route.id}`, { method: "POST" });
  };
  return (
    <>
      {routes.map((r) => {
        const start: [number, number] = [r.start.lat, r.start.lng];
        const end: [number, number] = [r.end.lat, r.end.lng];
        return (
          <React.Fragment key={r.id}>
            <Polyline positions={[start, end]} pathOptions={{ color: ROUTE_COLOR, weight: 3, dashArray: "8 5", opacity: 0.85 }}>
              <Tooltip sticky>{r.name}</Tooltip>
            </Polyline>
            <CircleMarker center={start} radius={7} pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.9, weight: 2 }}>
              <Popup>
                <div style={popupWrap}>
                  <strong style={{ fontSize: 13 }}>🚛 {r.name}</strong>
                  <div style={{ fontSize: 11, color: "#999", margin: "2px 0 8px" }}>Start: {r.start.lat.toFixed(4)}, {r.start.lng.toFixed(4)}<br />End: {r.end.lat.toFixed(4)}, {r.end.lng.toFixed(4)}</div>
                  <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={() => openEscortDialog(r)}>✈ Plan Escort Mission</button>
                  <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteConvoyRoute(r.id))}>🗑 Remove Route</button>
                </div>
              </Popup>
            </CircleMarker>
            <CircleMarker center={end} radius={5} pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.7, weight: 2 }} />
          </React.Fragment>
        );
      })}
    </>
  );
}

export default function DropZoneLayer() {
  return (
    <>
      <DropZoneMarkers />
      <ConvoyRouteMarkers />
      <MapRightClickHandler />
    </>
  );
}
"""

with open(
    "H:/Dokumenter/GitHub/dcs-retribution2/client/src/components/dropzonelayer/DropZoneLayer.tsx",
    "w",
    encoding="utf-8",
) as f:
    f.write(content)

print("done")
