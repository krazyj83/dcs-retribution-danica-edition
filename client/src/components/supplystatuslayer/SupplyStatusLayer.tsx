import { useEffect } from "react";
import { CircleMarker, LayerGroup, Tooltip } from "react-leaflet";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { fetchSupplyStatus, selectSupplyStatus } from "../../api/supplyStatusSlice";
import { isEnemy, ringOpacity, statusColor, supplyLines, supplyTitle } from "./supplyText";

// A coloured ring around every friendly base: green = fine, amber = low,
// red = critical (see game/logistics/supply_status.py). Enemy bases get a
// dotted ring while there is recent recon on them, fading as it ages
// (game/logistics/intel.py). The ring has no fill, so the base icon inside
// it stays clickable; hover the ring for numbers.
export default function SupplyStatusLayer() {
  const dispatch = useAppDispatch();
  const bases = useAppSelector(selectSupplyStatus);

  // Loaded once here; game loads and new turns bring fresh data, and the
  // server sends supply_status_changed when stock changes mid-turn
  // (api/eventstream.tsx), so there is no polling.
  useEffect(() => {
    dispatch(fetchSupplyStatus()).catch(() => undefined);
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
              opacity: ringOpacity(b),
              fill: false,
              dashArray: isEnemy(b) ? "2 6" : b.status === "critical" ? "6 4" : undefined,
            }}
          >
            <Tooltip direction="top" offset={[0, -20]}>
              <strong>{supplyTitle(b)}</strong>
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
