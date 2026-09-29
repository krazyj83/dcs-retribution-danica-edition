import type { BaseSupply } from "../../api/supplyStatusSlice";

export const STATUS_COLORS: Record<string, string> = {
  ok: "#27ae60",
  low: "#f39c12",
  critical: "#e74c3c",
};

export function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.ok;
}

export function statusLabel(status: string): string {
  if (status === "critical") return "Critical";
  if (status === "low") return "Low";
  return "OK";
}

function amount(quantity: number, capacity: number): string {
  return `${Math.round(quantity)} / ${Math.round(capacity)}`;
}

export function isEnemy(b: BaseSupply): boolean {
  return b.side === "red";
}

export function intelAgeText(age: number | null | undefined): string {
  if (!age) return "recon from this turn";
  return `recon ${age} turn${age > 1 ? "s" : ""} old`;
}

// Enemy rings fade as the recon report gets older.
export function ringOpacity(b: BaseSupply): number {
  if (!isEnemy(b)) return b.status === "ok" ? 0.6 : 0.95;
  return Math.max(0.3, 0.9 - 0.15 * (b.intel_age ?? 0));
}

export function supplyTitle(b: BaseSupply): string {
  if (isEnemy(b)) {
    return `${b.name} — enemy supply ${statusLabel(b.status)} (${intelAgeText(b.intel_age)})`;
  }
  return `${b.name} — supply ${statusLabel(b.status)}`;
}

// The lines shown when hovering a base's ring.
export function supplyLines(b: BaseSupply): string[] {
  if (isEnemy(b)) {
    const lines = [
      `Fuel ~${Math.round(b.fuel / 10) * 10}%`,
      `Ammunition ~${Math.round(b.ammunition / 10) * 10}%`,
    ];
    if (b.reasons.length > 0) lines.push(`⚠ ${b.reasons.join(", ")}`);
    return lines;
  }
  let fuel = `Fuel ${amount(b.fuel, b.fuel_capacity)}`;
  if (b.unlimited_fuel) {
    fuel += " (unlimited)";
  } else if (b.fuel_turns_left != null) {
    fuel += ` · ~${b.fuel_turns_left.toFixed(1)} turns left`;
  }
  const lines = [
    fuel,
    `Ammunition ${amount(b.ammunition, b.ammunition_capacity)}`,
    `Supplies ${amount(b.supplies, b.supplies_capacity)}`,
  ];
  if (b.reasons.length > 0) {
    lines.push(`⚠ ${b.reasons.join(", ")}`);
  }
  return lines;
}
