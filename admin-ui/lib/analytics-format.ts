/**
 * Pure helpers for turning the analytics API's string decimals into
 * dashboard-ready deltas, axis labels and grouped figures. Kept DOM-free so
 * they sit under the lib coverage gate.
 */
import type { AnalyticsGranularity, AnalyticsRange } from "./api-types";

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

/** Group an amount with thousands separators, rounded to whole units. */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/**
 * Shorten a figure for an axis tick or a donut centre: 1.2k, 12k, 3.1M, 1.2B.
 *
 * Drops the decimal once the mantissa reaches two digits (so `1.2k` but `12k`),
 * which keeps every tick down a y axis to roughly the same width — a column of
 * labels alternating between `1.2k` and `12.4k` reads as ragged.
 */
export function abbreviateNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  const scale = (divisor: number, suffix: string) =>
    (value / divisor).toFixed(magnitude >= divisor * 10 ? 0 : 1).replace(/\.0$/, "") + suffix;
  if (magnitude >= 1e9) return scale(1e9, "B");
  if (magnitude >= 1e6) return scale(1e6, "M");
  if (magnitude >= 1e3) return scale(1e3, "k");
  return String(Math.round(value));
}

/** `part` as a percentage of `total`, to one decimal. Zero total reads "0.0%". */
export function sharePercent(part: number, total: number): string {
  if (!total) return "0.0%";
  return `${((part / total) * 100).toFixed(1)}%`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Shorten an API bucket key into an axis label.
 *
 * Parsed textually rather than through `Date`, because `new Date("2026-08-17")`
 * is UTC midnight and would render as the 16th for any admin west of Greenwich
 * — an off-by-one-day axis on every chart.
 *
 * Weeks are labelled by their start date rather than an ISO week number: the
 * backend's bucket key is a date, and deriving "W33" from it means
 * reimplementing ISO week arithmetic for a label nobody reconciles against.
 *
 * @param bucket - the API bucket key, e.g. `2026-08-17` or `2026-08-17T14:00:00Z`
 * @param granularity - day/week/month, which picks the label shape
 * @param range - a 24h range labels by hour instead of by date
 * @returns a short label, or the raw bucket when it doesn't parse as a date
 */
export function formatBucketLabel(
  bucket: string,
  granularity: AnalyticsGranularity,
  range?: AnalyticsRange,
): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(bucket);
  if (!match) return bucket;
  const [, , month, day, hour] = match;
  if (range === "24h" && hour !== undefined) return `${hour}:00`;
  if (granularity === "month") return MONTHS[Number(month) - 1] ?? bucket;
  return `${Number(month)}/${Number(day)}`;
}

/** Human caption for the selected range, e.g. "Last 30 days". */
export function rangeLabel(range: AnalyticsRange): string {
  switch (range) {
    case "24h":
      return "Last 24 hours";
    case "7d":
      return "Last 7 days";
    case "30d":
      return "Last 30 days";
    case "quarter":
      return "This quarter";
  }
}
