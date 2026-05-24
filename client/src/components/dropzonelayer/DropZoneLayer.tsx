import { LatLng, DivIcon } from "leaflet";
import React, { useRef, useState } from "react";
import { CircleMarker, Marker, Polyline, Popup, Tooltip, useMapEvents } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { DropZone, createDropZone, deleteDropZone, selectDropZones, serverBase } from "../../api/dropZonesSlice";
import { createConvoyRoute, deleteConvoyRoute, selectConvoyRoutes } from "../../api/convoyRoutesSlice";
import type { ConvoyRoute } from "../../api/convoyRoutesSlice";

const popupWrap: React.CSSProperties = { minWidth: 210 };

const menuWrap: React.CSSProperties = {
  minWidth: 200,
  padding: "4px 0",
  background: "#1a252f",
  borderRadius: 4,
  border: "1px solid #3d566e",
};

const menuItem: React.CSSProperties = {
  display: "block",
  width: "100%",
  background: "transparent",
  color: "#ecf0f1",
  border: "none",
  borderRadius: 0,
  padding: "9px 14px",
  cursor: "pointer",
  fontSize: 13,
  textAlign: "left",
};

const menuDivider: React.CSSProperties = {
  borderTop: "1px solid #3d566e",
  margin: "4px 0",
};

const menuTitle: React.CSSProperties = {
  color: "#7f8c8d",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: 1,
  padding: "6px 14px 2px",
};


const btn: React.CSSProperties = {
  background: "#2c3e50",
  color: "#ecf0f1",
  border: "1px solid #3d566e",
  borderRadius: 4,
  padding: "5px 10px",
  cursor: "pointer",
  fontSize: 12,
};

const dangerBtn: React.CSSProperties = { ...btn, background: "#7b241c", border: "1px solid #922b21" };
const ROUTE_COLOR = "#f5a623";
const PENDING_COLOR = "#ecf0f1";
const DZ_COLOR = "#27ae60";

// Green diamond SVG icon for drop zones
function makeDiamondIcon(color: string, size: number = 18) {
  const half = size / 2;
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${size}' viewBox='0 0 ${size} ${size}'>
    <polygon points='${half},2 ${size - 2},${half} ${half},${size - 2} 2,${half}'
      fill='${color}' stroke='#fff' stroke-width='1.5'/>
  </svg>`;
  return new DivIcon({
    html: svg,
    className: "",
    iconSize: [size, size],
    iconAnchor: [half, half],
    popupAnchor: [0, -half],
  });
}

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
      setTimeout(() => setMenu(null), 50);
    },
  });

  if (menu && !route) {
    const onAddDropZone = () => {
      const name = window.prompt("Drop zone name (e.g. DZ Alpha):", "Drop Zone");
      if (name === null) { setMenu(null); return; }
      dispatch(createDropZone({
        name: name.trim() || "Drop Zone",
        lat: menu.latlng.lat,
        lng: menu.latlng.lng,
      }));
      setMenu(null);
    };
    const onAddConvoyRoute = () => {
      const startLatlng = menu.latlng;
      setMenu(null);
      setTimeout(() => setRoute({ step: "start", latlng: startLatlng }), 100);
    };
    return (
      <Popup position={menu.latlng} eventHandlers={{ remove: () => setMenu(null) }} closeButton={false}>
        <div style={menuWrap}>
          <div style={menuTitle}>Map actions</div>
          <button
            style={menuItem}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            onClick={onAddDropZone}
          >
            🎯 Add Drop Zone
          </button>
          <div style={menuDivider} />
          <button
            style={menuItem}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            onClick={onAddConvoyRoute}
          >
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
      const name = window.prompt("Name this convoy route:", "Convoy Route");
      if (name !== null) {
        dispatch(createConvoyRoute({ name: name.trim() || "Convoy Route", start_lat: route.start.lat, start_lng: route.start.lng, end_lat: route.end.lat, end_lng: route.end.lng }));
      }
      setRoute(null);
    };
    confirm();
    return (
      <>
        <Polyline positions={[route.start, route.end]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }} />
        <CircleMarker center={route.start} radius={6} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
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
        <Marker
          key={dz.id}
          position={[dz.position.lat, dz.position.lng]}
          icon={makeDiamondIcon(DZ_COLOR, 20)}
        >
          <Tooltip sticky>{dz.name}</Tooltip>
          <Popup>
            <div style={popupWrap}>
              <strong style={{ fontSize: 13, color: "#ecf0f1" }}>🎯 {dz.name}</strong>
              <div style={{ fontSize: 11, color: "#7f8c8d", margin: "2px 0 8px" }}>
                {dz.position.lat.toFixed(4)}, {dz.position.lng.toFixed(4)}
              </div>
              <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={() => openPackageDialog(dz)}>
                📋 Create Mission
              </button>
              <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteDropZone(dz.id))}>
                🗑 Remove Drop Zone
              </button>
            </div>
          </Popup>
        </Marker>
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
            <Marker position={start} icon={makeDiamondIcon(ROUTE_COLOR, 18)}>
              <Popup>
                <div style={popupWrap}>
                  <strong style={{ fontSize: 13, color: "#ecf0f1" }}>🚛 {r.name}</strong>
                  <div style={{ fontSize: 11, color: "#7f8c8d", margin: "2px 0 8px" }}>
                    Start: {r.start.lat.toFixed(4)}, {r.start.lng.toFixed(4)}<br />
                    End: &nbsp;{r.end.lat.toFixed(4)}, {r.end.lng.toFixed(4)}
                  </div>
                  <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={() => openEscortDialog(r)}>
                    ✈ Plan Escort Mission
                  </button>
                  <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteConvoyRoute(r.id))}>
                    🗑 Remove Route
                  </button>
                </div>
              </Popup>
            </Marker>
            <Marker position={end} icon={makeDiamondIcon(ROUTE_COLOR, 14)} />
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
