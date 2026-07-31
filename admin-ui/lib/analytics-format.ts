/**
 * Pure helpers for turning the analytics API's string decimals into
 * dashboard-ready deltas. Kept DOM-free so they sit under the lib coverage
 * gate.
 */

export type DeltaDirection = "up" | "down" | "flat";

/**
 * Percent change of `current` vs `previous`. Returns null when there is no
 * baseline (previous == 0), because "∞%" is meaningless on a tile.
 */
export function percentDelta(current: string, previous: string): number | null {
  const cur = Number(current);
  const prev = Number(previous);
  if (prev === 0) return null;
  return ((cur - prev) / prev) * 100;
}

/**
 * Format a percent delta into a label + direction for the tile chip.
 */
export function formatDelta(delta: number | null): {
  label: string;
  direction: DeltaDirection;
} {
  if (delta === null) return { label: "—", direction: "flat" };
  const direction: DeltaDirection = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const sign = delta > 0 ? "+" : "";
  return { label: `${sign}${delta.toFixed(1)}%`, direction };
}
