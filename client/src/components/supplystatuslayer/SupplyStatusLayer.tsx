import { useEffect } from "react";
import { CircleMarker, LayerGroup, Tooltip } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { fetchSupplyStatus, selectSupplyStatus } from "../../api/supplyStatusSlice";
import { statusColor, statusLabel, supplyLines } from "./supplyText";

const REFRESH_MS = 15000;

// A coloured ring around every friendly base: green = fine, amber = low,
// red = critical (see game/logistics/supply_status.py). The ring has no fill,
// so the base icon inside it stays clickable; hover the ring for numbers.
export default function SupplyStatusLayer() {
  const dispatch = useAppDispatch();
  const bases = useAppSelector(selectSupplyStatus);

  useEffect(() => {
    const refresh = () => {
      dispatch(fetchSupplyStatus()).catch(() => undefined);
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [dispatch]);

  return (
    <LayerGroup>
      {bases.map((b) => {
        const color = statusColor(b.status);
        return (
          <CircleMarker
            key={b.id}
            center={[b.position.lat, b.position.lng]}
            radius={b.status === "critical" ? 22 : 19}
            pathOptions={{
              color,
              weight: b.status === "ok" ? 2 : 4,
              opacity: b.status === "ok" ? 0.6 : 0.95,
              fill: false,
              dashArray: b.status === "critical" ? "6 4" : undefined,
            }}
          >
            <Tooltip direction="top" offset={[0, -20]}>
              <strong>
                {b.name} — supply {statusLabel(b.status)}
              </strong>
              {supplyLines(b).map((line) => (
                <div key={line}>{line}</div>
              ))}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </LayerGroup>
  );
}
