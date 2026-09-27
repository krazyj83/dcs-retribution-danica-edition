import { LatLng, DivIcon, DomEvent } from "leaflet";
import React, { useEffect, useRef, useState } from "react";
import { CircleMarker, LayerGroup, Marker, Polyline, Popup, Tooltip, useMapEvents } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { DropZone, createDropZone, deleteDropZone, selectDropZones, serverBase } from "../../api/dropZonesSlice";
import { createConvoyRoute, deleteConvoyRoute, selectConvoyRoutes } from "../../api/convoyRoutesSlice";
import type { ConvoyRoute } from "../../api/convoyRoutesSlice";
import { describeDrive } from "./convoyTime";

// Dark panel, like the right-click menu: the light title text was unreadable
// on Leaflet's default white popup.
const popupWrap: React.CSSProperties = {
  minWidth: 210,
  padding: "8px 10px",
  background: "#1a252f",
  borderRadius: 4,
  border: "1px solid #3d566e",
};

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

// What the right-click workflow is doing right now.
//  menu        - the "Map actions" popup is open
//  dz-name     - asking for the name of a new drop zone
//  route-start - start point placed, waiting for a right-click on the end point
//  route-name  - both points placed, asking for the route name
type Pending =
  | { kind: "menu"; latlng: LatLng }
  | { kind: "dz-name"; latlng: LatLng }
  | { kind: "route-start"; start: LatLng; cursor?: LatLng }
  | { kind: "route-name"; start: LatLng; end: LatLng };

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 8,
  background: "#1a252f",
  color: "#ecf0f1",
  border: "1px solid #3d566e",
  borderRadius: 3,
  padding: "5px 7px",
  fontSize: 12,
  boxSizing: "border-box",
};

const errorStyle: React.CSSProperties = {
  color: "#e74c3c",
  fontSize: 11,
  marginTop: 6,
};

const infoStyle: React.CSSProperties = {
  color: "#bdc3c7",
  fontSize: 11,
  marginTop: 4,
};

function errorText(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return String(err);
}

// A small name form shown inside a map popup. It replaces window.prompt,
// which goes through Qt's javaScriptPrompt and does not reliably hand the
// typed text back to the page.
export function NameForm(props: {
  title: string;
  info?: string;
  defaultName: string;
  onSave: (name: string) => Promise<void>;
  onCancel: () => void;
}) {
  const { title, info, defaultName, onSave, onCancel } = props;
  const [name, setName] = useState(defaultName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    const el = formRef.current;
    if (!el) return;
    // Keep typing, clicks and scrolling inside the form away from the map
    // (otherwise "+"/"-" zoom the map and a click closes the popup).
    DomEvent.disableClickPropagation(el);
    DomEvent.disableScrollPropagation(el);
    const onKey = (e: KeyboardEvent) => {
      e.stopPropagation();
      if (e.key === "Escape") cancelRef.current();
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSave(name.trim() || defaultName);
    } catch (err) {
      console.error(`${title} failed: ${errorText(err)}`);
      setError(errorText(err));
      setBusy(false);
    }
  };

  return (
    <form ref={formRef} style={popupWrap} onSubmit={submit}>
      <strong style={{ fontSize: 13, color: "#ecf0f1" }}>{title}</strong>
      {info && <div style={infoStyle}>{info}</div>}
      <input
        autoFocus
        aria-label="Name"
        style={inputStyle}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onFocus={(e) => e.target.select()}
      />
      {error && <div style={errorStyle}>Could not save: {error}</div>}
      <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <button type="submit" style={btn} disabled={busy}>
          ✔ Save
        </button>
        <button type="button" style={btn} onClick={onCancel}>
          ✖ Cancel
        </button>
      </div>
    </form>
  );
}

function MapRightClickHandler() {
  const dispatch = useAppDispatch();
  const [pending, setPending] = useState<Pending | null>(null);
  const cancel = () => setPending(null);

  useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      setPending((p) =>
        p?.kind === "route-start"
          ? { kind: "route-name", start: p.start, end: e.latlng }
          : { kind: "menu", latlng: e.latlng }
      );
    },
    click() {
      // A left-click on the map closes the menu; a route in progress stays.
      setPending((p) => (p?.kind === "menu" ? null : p));
    },
    mousemove(e) {
      // While placing the end point, draw a live line with the drive time.
      setPending((p) =>
        p?.kind === "route-start" ? { ...p, cursor: e.latlng } : p
      );
    },
    keydown(e) {
      if (e.originalEvent.key === "Escape") setPending(null);
    },
  });

  if (pending === null) return null;

  // The name forms are closed only by Save, Cancel or Esc, never by Leaflet
  // removing a popup: when the menu popup closes and the drop zone form opens
  // at the same spot, Leaflet reports a popup removal right after the switch,
  // which used to wipe the brand-new form before it was shown.

  if (pending.kind === "menu") {
    const latlng = pending.latlng;
    return (
      <Popup key="menu" position={latlng} closeButton={false}>
        <div style={menuWrap}>
          <div style={menuTitle}>Map actions</div>
          <button
            style={menuItem}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            onClick={() => setPending({ kind: "dz-name", latlng })}
          >
            🎯 Add Drop Zone
          </button>
          <div style={menuDivider} />
          <button
            style={menuItem}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            onClick={() => setPending({ kind: "route-start", start: latlng })}
          >
            🚛 Add Convoy Route
          </button>
        </div>
      </Popup>
    );
  }

  if (pending.kind === "dz-name") {
    const latlng = pending.latlng;
    const save = async (name: string) => {
      await dispatch(createDropZone({ name, lat: latlng.lat, lng: latlng.lng })).unwrap();
      setPending(null);
    };
    return (
      <>
        <Marker position={latlng} icon={makeDiamondIcon(PENDING_COLOR, 20)} />
        <Popup key="dz-name" position={latlng} closeButton={false} autoClose={false} closeOnClick={false}>
          <NameForm title="🎯 New Drop Zone" defaultName="Drop Zone" onSave={save} onCancel={cancel} />
        </Popup>
      </>
    );
  }

  if (pending.kind === "route-start") {
    const cursor = pending.cursor;
    return (
      <>
        {cursor && (
          <Polyline positions={[pending.start, cursor]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }}>
            <Tooltip permanent direction="right" offset={[12, 0]}>
              {describeDrive(pending.start, cursor)}
            </Tooltip>
          </Polyline>
        )}
      <CircleMarker center={pending.start} radius={8} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
        <Tooltip permanent direction="top" offset={[0, -12]}>
          Route start — right-click to set end point (Esc cancels)
        </Tooltip>
      </CircleMarker>
      </>
    );
  }

  const { start, end } = pending;
  const save = async (name: string) => {
    await dispatch(
      createConvoyRoute({ name, start_lat: start.lat, start_lng: start.lng, end_lat: end.lat, end_lng: end.lng })
    ).unwrap();
    setPending(null);
  };
  return (
    <>
      <Polyline positions={[start, end]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }} />
      <CircleMarker center={start} radius={6} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
      <Popup key="route-name" position={end} closeButton={false} autoClose={false} closeOnClick={false}>
        <NameForm title="🚛 New Convoy Route" info={describeDrive(start, end)} defaultName="Convoy Route" onSave={save} onCancel={cancel} />
      </Popup>
    </>
  );
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
              <Tooltip sticky>
                {r.name} — {describeDrive(r.start, r.end)}
              </Tooltip>
            </Polyline>
            <Marker position={start} icon={makeDiamondIcon(ROUTE_COLOR, 18)}>
              <Popup>
                <div style={popupWrap}>
                  <strong style={{ fontSize: 13, color: "#ecf0f1" }}>🚛 {r.name}</strong>
                  <div style={{ fontSize: 11, color: "#7f8c8d", margin: "2px 0 8px" }}>
                    Start: {r.start.lat.toFixed(4)}, {r.start.lng.toFixed(4)}<br />
                    End: &nbsp;{r.end.lat.toFixed(4)}, {r.end.lng.toFixed(4)}
                  </div>
                  <div style={{ ...infoStyle, margin: "0 0 8px" }}>
                    🕒 {describeDrive(r.start, r.end)}
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

// Everything is drawn inside one LayerGroup: a LayersControl overlay takes a
// single layer, and loose markers each registered themselves as a new
// "Drop zones & Convoy routes" entry in the layer list.
export default function DropZoneLayer() {
  return (
    <LayerGroup>
      <DropZoneMarkers />
      <ConvoyRouteMarkers />
      <MapRightClickHandler />
    </LayerGroup>
  );
}
