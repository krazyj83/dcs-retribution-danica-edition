// Drive time estimate for a player-drawn convoy route.
//
// The convoy drives at CONVOY_SPEED_KPH (same value as CONVOY_SPEED in
// game/missiongenerator/playerconvoygenerator.py). DCS picks the road route
// itself, so the map only knows the straight-line distance; roads are usually
// 20-50% longer than the straight line, which gives the time range shown.

export const CONVOY_SPEED_KPH = 40;
export const ROAD_FACTOR_MIN = 1.2;
export const ROAD_FACTOR_MAX = 1.5;

const EARTH_RADIUS_KM = 6371;

export interface Position {
  lat: number;
  lng: number;
}

/** Great-circle distance between two map positions, in km. */
export function straightLineKm(a: Position, b: Position): number {
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

export interface DriveEstimate {
  km: number;
  minMinutes: number;
  maxMinutes: number;
}

/** Straight-line length of a path, leg by leg, in km. */
export function pathKm(points: Position[]): number {
  let km = 0;
  for (let i = 1; i < points.length; i++) {
    km += straightLineKm(points[i - 1], points[i]);
  }
  return km;
}

export function driveEstimate(a: Position, b: Position): DriveEstimate {
  return pathEstimate([a, b]);
}

/** Drive time along a path through waypoints. */
export function pathEstimate(points: Position[]): DriveEstimate {
  const km = pathKm(points);
  const minutes = (factor: number) =>
    Math.round(((km * factor) / CONVOY_SPEED_KPH) * 60);
  return {
    km,
    minMinutes: minutes(ROAD_FACTOR_MIN),
    maxMinutes: minutes(ROAD_FACTOR_MAX),
  };
}

export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** e.g. "23 km · about 41 min – 52 min by road at 40 km/h" */
export function describeDrive(a: Position, b: Position): string {
  return describePath([a, b]);
}

/** The same for a path through waypoints. */
export function describePath(points: Position[]): string {
  const e = pathEstimate(points);
  const km = e.km < 10 ? e.km.toFixed(1) : Math.round(e.km).toString();
  return (
    `${km} km · about ${formatMinutes(e.minMinutes)} – ` +
    `${formatMinutes(e.maxMinutes)} by road at ${CONVOY_SPEED_KPH} km/h`
  );
}
