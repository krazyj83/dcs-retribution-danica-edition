import { LatLng, DivIcon, DomEvent } from "leaflet";
import React, { useEffect, useRef, useState } from "react";
import { CircleMarker, LayerGroup, Marker, Polyline, Popup, Tooltip, useMapEvents } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { DropZone, createDropZone, deleteDropZone, selectDropZones, serverBase } from "../../api/dropZonesSlice";
import { createConvoyRoute, deleteConvoyRoute, routePath, selectConvoyRoutes, setConvoyRouteRepeat } from "../../api/convoyRoutesSlice";
import type { ConvoyRoute } from "../../api/convoyRoutesSlice";
import { setOverlayState } from "../../api/mapSlice";
import { describePath } from "./convoyTime";

// Name of the layer-list check box that shows drop zones and convoy routes.
export const DROP_ZONE_OVERLAY = "Drop zones & Convoy routes";

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

// Marker sizes in pixels. Doubled from the first version (20/18/14): the
// small diamonds were easy to lose among the base and SAM icons.
export const DZ_ICON_SIZE = 40;
const ROUTE_START_ICON_SIZE = 36;
const ROUTE_END_ICON_SIZE = 28;
const PENDING_START_RADIUS = 16;
const PENDING_DOT_RADIUS = 12;
const PENDING_VIA_RADIUS = 9;
const ROUTE_VIA_RADIUS = 7;

// Diamond SVG icon for drop zones and route ends
function makeDiamondIcon(color: string, size: number = 36) {
  const half = size / 2;
  const inset = Math.max(2, Math.round(size / 10));
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${size}' viewBox='0 0 ${size} ${size}'>
    <polygon points='${half},${inset} ${size - inset},${half} ${half},${size - inset} ${inset},${half}'
      fill='${color}' stroke='#fff' stroke-width='2.5'/>
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
//  route-start - start point placed: left-clicks add waypoints, a right-click
//                sets the end point
//  route-name  - all points placed, asking for the route name
type Pending =
  | { kind: "menu"; latlng: LatLng }
  | { kind: "dz-name"; latlng: LatLng }
  | { kind: "route-start"; start: LatLng; via: LatLng[]; cursor?: LatLng }
  | { kind: "route-name"; start: LatLng; via: LatLng[]; end: LatLng };

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
  // Show a "Repeat every turn" tick box (convoy routes).
  repeatOption?: boolean;
  onSave: (name: string, repeat: boolean) => Promise<void>;
  onCancel: () => void;
}) {
  const { title, info, defaultName, repeatOption, onSave, onCancel } = props;
  const [name, setName] = useState(defaultName);
  const [repeat, setRepeat] = useState(false);
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
      await onSave(name.trim() || defaultName, repeat);
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
      {repeatOption && (
        <label style={{ ...infoStyle, display: "flex", alignItems: "center", gap: 6, marginTop: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} />
          ↻ Repeat every turn (standing supply line)
        </label>
      )}
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

// The right-click menu lives outside the "Drop zones & Convoy routes" overlay
// (see LiberationMap), so the menu and the orange preview are always visible.
// Choosing an action ticks that overlay again: with it unticked the menu still
// worked and the server saved the zone or route, but the result was drawn on a
// hidden layer, so nothing seemed to happen.
export function MapRightClickHandler() {
  const dispatch = useAppDispatch();
  const [pending, setPending] = useState<Pending | null>(null);
  const cancel = () => setPending(null);
  // When route drawing started: the click on the menu's "Add Convoy Route"
  // button must not also count as the first waypoint.
  const routeStartedAt = useRef(0);
  const drawingRoute = pending?.kind === "route-start";

  // Backspace and Esc while drawing a route, wherever the keyboard focus is
  // (the map only gets key events while it has focus).
  useEffect(() => {
    if (!drawingRoute) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPending(null);
      if (e.key === "Backspace") {
        e.preventDefault();
        setPending((p) =>
          p?.kind === "route-start" && p.via.length > 0
            ? { ...p, via: p.via.slice(0, -1) }
            : p
        );
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawingRoute]);
  const showLayer = () =>
    dispatch(setOverlayState({ name: DROP_ZONE_OVERLAY, checked: true }));

  useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      setPending((p) =>
        p?.kind === "route-start"
          ? { kind: "route-name", start: p.start, via: p.via, end: e.latlng }
          : { kind: "menu", latlng: e.latlng }
      );
    },
    click(e) {
      // A left-click on the map closes the menu, and adds a waypoint to a
      // route being drawn.
      const justStarted = Date.now() - routeStartedAt.current < 400;
      setPending((p) => {
        if (p?.kind === "menu") return null;
        if (p?.kind === "route-start" && !justStarted)
          return { ...p, via: [...p.via, e.latlng] };
        return p;
      });
    },
    mousemove(e) {
      // While placing the end point, draw a live line with the drive time.
      setPending((p) =>
        p?.kind === "route-start" ? { ...p, cursor: e.latlng } : p
      );
    },
    keydown(e) {
      // While drawing a route the window listener above handles the keys.
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
            onClick={() => {
              showLayer();
              setPending({ kind: "dz-name", latlng });
            }}
          >
            🎯 Add Drop Zone
          </button>
          <div style={menuDivider} />
          <button
            style={menuItem}
            onMouseEnter={(e) => (e.currentTarget.style.background = "#2c3e50")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            onClick={() => {
              showLayer();
              routeStartedAt.current = Date.now();
              setPending({ kind: "route-start", start: latlng, via: [] });
            }}
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
      showLayer();
      setPending(null);
    };
    return (
      <>
        <Marker position={latlng} icon={makeDiamondIcon(PENDING_COLOR, DZ_ICON_SIZE)} />
        <Popup key="dz-name" position={latlng} closeButton={false} autoClose={false} closeOnClick={false}>
          <NameForm title="🎯 New Drop Zone" defaultName="Drop Zone" onSave={save} onCancel={cancel} />
        </Popup>
      </>
    );
  }

  if (pending.kind === "route-start") {
    const { cursor, via } = pending;
    const placed = [pending.start, ...via];
    const lastPlaced = placed[placed.length - 1];
    return (
      <>
        {via.length > 0 && (
          <Polyline positions={placed} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.9 }} />
        )}
        {cursor && (
          <Polyline positions={[lastPlaced, cursor]} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }}>
            <Tooltip permanent direction="right" offset={[PENDING_START_RADIUS + 4, 0]}>
              {describePath([...placed, cursor])}
            </Tooltip>
          </Polyline>
        )}
        {via.map((p, i) => (
          <CircleMarker key={i} center={p} radius={PENDING_VIA_RADIUS} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
            <Tooltip direction="top">Waypoint {i + 1}</Tooltip>
          </CircleMarker>
        ))}
      <CircleMarker center={pending.start} radius={PENDING_START_RADIUS} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}>
        <Tooltip permanent direction="top" offset={[0, -(PENDING_START_RADIUS + 4)]}>
          Route start{via.length > 0 ? ` · ${via.length} waypoint${via.length > 1 ? "s" : ""} so far` : ""}
          <br />
          Left-click: add waypoint · Right-click: set end · Backspace: undo · Esc: cancel
        </Tooltip>
      </CircleMarker>
      </>
    );
  }

  const { start, via, end } = pending;
  const path = [start, ...via, end];
  const save = async (name: string, repeat: boolean) => {
    await dispatch(
      createConvoyRoute({
        name,
        start_lat: start.lat,
        start_lng: start.lng,
        end_lat: end.lat,
        end_lng: end.lng,
        repeat,
        via: via.map((p) => ({ lat: p.lat, lng: p.lng })),
      })
    ).unwrap();
    showLayer();
    setPending(null);
  };
  const info = via.length > 0 ? `${describePath(path)} · ${via.length} waypoint${via.length > 1 ? "s" : ""}` : describePath(path);
  return (
    <>
      <Polyline positions={path} pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }} />
      <CircleMarker center={start} radius={PENDING_DOT_RADIUS} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
      {via.map((p, i) => (
        <CircleMarker key={i} center={p} radius={PENDING_VIA_RADIUS} pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }} />
      ))}
      <Popup key="route-name" position={end} closeButton={false} autoClose={false} closeOnClick={false}>
        <NameForm title="🚛 New Convoy Route" info={info} defaultName="Convoy Route" repeatOption onSave={save} onCancel={cancel} />
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
          icon={makeDiamondIcon(DZ_COLOR, DZ_ICON_SIZE)}
        >
          <Tooltip sticky>
            {dz.name}
            {dz.cache && dz.cache.length > 0 ? " 📦" : ""}
          </Tooltip>
          <Popup>
            <div style={popupWrap}>
              <strong style={{ fontSize: 13, color: "#ecf0f1" }}>🎯 {dz.name}</strong>
              <div style={{ fontSize: 11, color: "#7f8c8d", margin: "2px 0 8px" }}>
                {dz.position.lat.toFixed(4)}, {dz.position.lng.toFixed(4)}
                {dz.base ? ` · supplies ${dz.base}` : ""}
              </div>
              {dz.cache && dz.cache.length > 0 && (
                <div style={{ fontSize: 12, color: "#ecf0f1", margin: "0 0 8px" }}>
                  <div style={{ color: "#f5a623", fontWeight: 600 }}>📦 Forward cache</div>
                  {dz.cache.map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                </div>
              )}
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
        const path = routePath(r);
        const via = r.via ?? [];
        return (
          <React.Fragment key={r.id}>
            {/* Standing routes are drawn solid, one-off routes dashed. */}
            <Polyline
              positions={path.map((p) => [p.lat, p.lng] as [number, number])}
              pathOptions={{ color: ROUTE_COLOR, weight: 3, dashArray: r.repeat ? undefined : "8 5", opacity: 0.85 }}
            >
              <Tooltip sticky>
                {r.repeat ? "↻ " : ""}
                {r.name} — {describePath(path)}
              </Tooltip>
            </Polyline>
            <Marker position={start} icon={makeDiamondIcon(ROUTE_COLOR, ROUTE_START_ICON_SIZE)}>
              <Popup>
                <div style={popupWrap}>
                  <strong style={{ fontSize: 13, color: "#ecf0f1" }}>
                    🚛 {r.name}
                  </strong>
                  <div style={{ ...infoStyle, margin: "2px 0 0" }}>
                    {r.repeat ? "↻ Standing route: a convoy drives it every turn" : "One-off: removed at the end of this turn"}
                  </div>
                  <div style={{ fontSize: 11, color: "#7f8c8d", margin: "2px 0 8px" }}>
                    Start: {r.start.lat.toFixed(4)}, {r.start.lng.toFixed(4)}<br />
                    End: &nbsp;{r.end.lat.toFixed(4)}, {r.end.lng.toFixed(4)}
                    {via.length > 0 && (
                      <>
                        <br />
                        Waypoints: {via.length}
                      </>
                    )}
                  </div>
                  <div style={{ ...infoStyle, margin: "0 0 8px" }}>
                    🕒 {describePath(path)}
                  </div>
                  <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={() => openEscortDialog(r)}>
                    ✈ Plan Escort Mission
                  </button>
                  <button
                    style={{ ...btn, width: "100%", marginBottom: 5 }}
                    onClick={() => dispatch(setConvoyRouteRepeat({ id: r.id, repeat: !r.repeat }))}
                  >
                    {r.repeat ? "⏹ Stop repeating" : "↻ Repeat every turn"}
                  </button>
                  <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteConvoyRoute(r.id))}>
                    🗑 Remove Route
                  </button>
                </div>
              </Popup>
            </Marker>
            {via.map((p, i) => (
              <CircleMarker
                key={i}
                center={[p.lat, p.lng]}
                radius={ROUTE_VIA_RADIUS}
                pathOptions={{ color: "#fff", weight: 2, fillColor: ROUTE_COLOR, fillOpacity: 1 }}
              >
                <Tooltip direction="top">
                  {r.name}: waypoint {i + 1} of {via.length}
                </Tooltip>
              </CircleMarker>
            ))}
            <Marker position={end} icon={makeDiamondIcon(ROUTE_COLOR, ROUTE_END_ICON_SIZE)} />
          </React.Fragment>
        );
      })}
    </>
  );
}

// The saved zones and routes are drawn inside one LayerGroup: a LayersControl
// overlay takes a single layer, and loose markers each registered themselves
// as a new "Drop zones & Convoy routes" entry in the layer list. The
// right-click handler is not in here; LiberationMap puts it on the map itself.
export default function DropZoneLayer() {
  return (
    <LayerGroup>
      <DropZoneMarkers />
      <ConvoyRouteMarkers />
    </LayerGroup>
  );
}
