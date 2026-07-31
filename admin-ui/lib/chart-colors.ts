/**
 * Chart color tokens for Recharts, derived from the brand palette so charts
 * respect per-tenant branding and dark/light mode. These reference CSS
 * variables set by the brand-palette injector; Recharts accepts any CSS color
 * string including `var(--...)`.
 */

/** Ordered categorical series colors (wrap around for >N series). */
export const CHART_SERIES = [
  "var(--chart-1, #48C2CF)",
  "var(--chart-2, #144989)",
  "var(--chart-3, #7C5CFC)",
  "var(--chart-4, #F5A623)",
  "var(--chart-5, #34C759)",
  "var(--chart-6, #FF6B6B)",
] as const;

/** Semantic colors for status breakdowns. */
export const STATUS_COLORS = {
  completed: "var(--chart-5, #34C759)",
  failed: "var(--chart-6, #FF6B6B)",
  pending: "var(--chart-4, #F5A623)",
} as const;

/**
 * Return the categorical color for a given series index, wrapping around the
 * palette so any number of series gets a stable color.
 */
export function seriesColor(index: number): string {
  return CHART_SERIES[index % CHART_SERIES.length];
}
