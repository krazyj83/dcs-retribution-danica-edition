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

// The lines shown when hovering a base's ring.
export function supplyLines(b: BaseSupply): string[] {
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
