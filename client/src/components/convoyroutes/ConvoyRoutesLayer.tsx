import { LatLng } from "leaflet";
import { useState } from "react";
import {
  CircleMarker,
  Polyline,
  Popup,
  Tooltip,
  useMapEvents,
} from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import {
  ConvoyRoute,
  createConvoyRoute,
  deleteConvoyRoute,
  selectConvoyRoutes,
} from "../../api/convoyRoutesSlice";
import { serverBase } from "../../api/dropZonesSlice";

const popupWrap: React.CSSProperties = { minWidth: 210 };

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

const dangerBtn: React.CSSProperties = { ...btn, background: "#7b241c" };

const ROUTE_COLOR = "#f5a623";
const PENDING_COLOR = "#ffffff";

type PendingRoute =
  | { step: "start"; latlng: LatLng }
  | { step: "end"; start: LatLng; end: LatLng; name: string };

function MapRightClickHandler() {
  const dispatch = useAppDispatch();
  const [pending, setPending] = useState<PendingRoute | null>(null);

  useMapEvents({
    contextmenu(e) {
      e.originalEvent.preventDefault();
      if (!pending) {
        setPending({ step: "start", latlng: e.latlng });
      } else if (pending.step === "start") {
        setPending({ step: "end", start: pending.latlng, end: e.latlng, name: "" });
      }
    },
    click() {
      if (pending?.step === "start") setPending(null);
    },
  });

  if (pending?.step === "start") {
    return (
      <CircleMarker
        center={pending.latlng}
        radius={8}
        pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 0.9, weight: 2 }}
      >
        <Tooltip permanent direction="top" offset={[0, -12]}>
          Route start — right-click to set end point
        </Tooltip>
      </CircleMarker>
    );
  }

  if (pending?.step === "end") {
    const confirm = () => {
      dispatch(createConvoyRoute({
        name: pending.name.trim() || "Convoy Route",
        start_lat: pending.start.lat,
        start_lng: pending.start.lng,
        end_lat: pending.end.lat,
        end_lng: pending.end.lng,
      }));
      setPending(null);
    };

    return (
      <>
        <Polyline
          positions={[pending.start, pending.end]}
          pathOptions={{ color: PENDING_COLOR, weight: 2, dashArray: "6 4", opacity: 0.7 }}
        />
        <CircleMarker
          center={pending.start}
          radius={6}
          pathOptions={{ color: PENDING_COLOR, fillColor: PENDING_COLOR, fillOpacity: 1 }}
        />
        <Popup position={pending.end} eventHandlers={{ remove: () => setPending(null) }}>
          <div style={popupWrap}>
            <strong style={{ fontSize: 13 }}>🚛 New Convoy Route</strong>
            <input
              autoFocus
              style={inputStyle}
              placeholder="Route name (e.g. MSR Alpha)"
              value={pending.name}
              onChange={(e) => setPending({ ...pending, name: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && confirm()}
            />
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <button style={btn} onClick={confirm}>✔ Create</button>
              <button style={{ ...btn, background: "#555" }} onClick={() => setPending(null)}>Cancel</button>
            </div>
          </div>
        </Popup>
      </>
    );
  }

  return null;
}

function ConvoyRouteMarker({ route }: { route: ConvoyRoute }) {
  const dispatch = useAppDispatch();

  const openEscortDialog = async () => {
    await fetch(`${serverBase()}/qt/create-package/convoy-route/${route.id}`, {
      method: "POST",
    });
  };

  const start: [number, number] = [route.start.lat, route.start.lng];
  const end: [number, number] = [route.end.lat, route.end.lng];

  return (
    <>
      <Polyline
        positions={[start, end]}
        pathOptions={{ color: ROUTE_COLOR, weight: 3, dashArray: "8 5", opacity: 0.85 }}
      >
        <Tooltip sticky>{route.name}</Tooltip>
      </Polyline>
      <CircleMarker
        center={start}
        radius={7}
        pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.9, weight: 2 }}
      >
        <Popup>
          <div style={popupWrap}>
            <strong style={{ fontSize: 13 }}>🚛 {route.name}</strong>
            <div style={{ fontSize: 11, color: "#999", margin: "2px 0 8px" }}>
              Start: {route.start.lat.toFixed(4)}, {route.start.lng.toFixed(4)}<br />
              End: &nbsp;{route.end.lat.toFixed(4)}, {route.end.lng.toFixed(4)}
            </div>
            <button style={{ ...btn, width: "100%", marginBottom: 5 }} onClick={openEscortDialog}>
              ✈ Plan Escort Mission
            </button>
            <button style={{ ...dangerBtn, width: "100%" }} onClick={() => dispatch(deleteConvoyRoute(route.id))}>
              🗑 Remove Route
            </button>
          </div>
        </Popup>
      </CircleMarker>
      <CircleMarker
        center={end}
        radius={5}
        pathOptions={{ color: ROUTE_COLOR, fillColor: ROUTE_COLOR, fillOpacity: 0.7, weight: 2 }}
      />
    </>
  );
}

export default function ConvoyRoutesLayer() {
  const routes = useAppSelector(selectConvoyRoutes);
  return (
    <>
      {routes.map((r) => <ConvoyRouteMarker key={r.id} route={r} />)}
      <MapRightClickHandler />
    </>
  );
}
