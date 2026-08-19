/**
 * Pure, domain-generic filtering + counting for the unified Approvals page
 * toolbar (1a design). Every one of the three maker-checker queues (config
 * requests, money operations, user operations) is first normalised to an
 * `ApprovalRow` so this module never imports a domain type and stays trivially
 * unit-testable without React.
 *
 * The toolbar drives four independent facets — status, type, date range, and a
 * free-text search — over the active tab's rows. Since B7.1/B7.2c the status
 * facet, the search, and the segment counts are SERVER-side (see
 * `lib/approvals-window.ts`); this module owns only the client facets (type,
 * date) applied to the fetched window via `applyFilters`.
 */

/** Preset windows for the date-range facet. `"all"` disables date filtering. */
export type DateRangeKey = "7d" | "30d" | "90d" | "all";

/** The four maker-checker lifecycle statuses, shared by all three queues. */
export const STATUS_KEYS = [
  "PENDING",
  "CHANGES_REQUESTED",
  "APPLIED",
  "WITHDRAWN",
] as const;

export type StatusKey = (typeof STATUS_KEYS)[number];

/**
 * A queue row reduced to just the fields the toolbar filters on. `type` is the
 * domain's facet value — a `config_type` for configuration, an operation code
 * for transactions/users — or `null` for a queue with no clean facet.
 */
export interface ApprovalRow {
  /** Request / operation id (also the search "request ID"). */
  id: string;
  /** Uppercased lifecycle status; unknown values simply never match a segment. */
  status: string;
  /** Domain facet value (config_type or operation code); null when facet-less. */
  type: string | null;
  /** ISO-8601 creation timestamp, used by the date-range facet. */
  createdAt: string;
  /** Maker display name (falls back to the raw id at the call site). */
  maker: string;
  /** Raw maker id, so a search by id still hits even when a name is shown. */
  makerId: string;
  /** One-line entity/summary text shown in the table. */
  summary: string;
}

/**
 * The CLIENT facet selections the toolbar owns: type and date. Status and
 * search are deliberately absent — status is a SERVER param since B7.1 and
 * search since B7.2c (each changes what window is fetched; see
 * `lib/approvals-window.ts`), so client filtering never re-applies them.
 */
export interface ApprovalFilters {
  /** Selected type codes — OR-matched; empty means "any type". */
  types: string[];
  /** Selected date-range preset. */
  dateRange: DateRangeKey;
}

/**
 * The neutral starting point. The date range defaults to `"all"` so a genuinely
 * old pending request is never hidden by an implicit window.
 */
export const DEFAULT_FILTERS: ApprovalFilters = {
  types: [],
  dateRange: "all",
};

/** Number of days in each bounded preset; `"all"` is unbounded (handled apart). */
const RANGE_DAYS: Record<Exclude<DateRangeKey, "all">, number> = {
  "7d": 7,
  "30d": 30,
  "90d": 90,
};

/**
 * The earliest `created_at` a row may carry to pass a date-range preset.
 *
 * @param range Selected preset.
 * @param now Reference "now" (injected so tests are deterministic).
 * @returns The cutoff `Date`, or `null` for `"all"` (no lower bound).
 */
export function dateRangeCutoff(range: DateRangeKey, now: Date): Date | null {
  if (range === "all") return null;
  const cutoff = new Date(now);
  cutoff.setDate(cutoff.getDate() - RANGE_DAYS[range]);
  return cutoff;
}

/**
 * Whether a row's creation time falls within the selected preset. The cutoff is
 * inclusive (`>=`), so a row created exactly at the boundary is kept. An
 * unparseable timestamp is treated as out-of-range for a bounded preset.
 */
export function withinDateRange(
  row: ApprovalRow,
  range: DateRangeKey,
  now: Date,
): boolean {
  const cutoff = dateRangeCutoff(range, now);
  if (!cutoff) return true;
  const created = new Date(row.createdAt).getTime();
  if (Number.isNaN(created)) return false;
  return created >= cutoff.getTime();
}

/**
 * Apply every client facet (type, date) to `rows`. The rows are the
 * server-fetched window, already status- and search-filtered server-side.
 * Pure — never mutates the input.
 *
 * @param rows Normalised rows for the active tab's fetched window.
 * @param filters The current facet selections.
 * @param now Reference "now" for the date facet (defaults to the wall clock).
 */
export function applyFilters(
  rows: ApprovalRow[],
  filters: ApprovalFilters,
  now: Date = new Date(),
): ApprovalRow[] {
  return rows.filter((row) => {
    if (filters.types.length > 0 && (row.type === null || !filters.types.includes(row.type))) {
      return false;
    }
    if (!withinDateRange(row, filters.dateRange, now)) return false;
    return true;
  });
}

/**
 * Pick the approvals tab to land on. An explicit `?tab=` request always wins
 * (it's a shareable URL); otherwise the first visible tab with pending work —
 * a checker opens this page to action something, not to stare at an empty
 * default queue — falling back to the first visible tab when nothing is
 * pending anywhere.
 *
 * @param tabs Visible tabs in display order, each with its pending count.
 * @param requested The raw `?tab=` search param, if any.
 * @returns The active tab key, or null when no tabs are visible.
 */
export function resolveActiveTab<K extends string>(
  tabs: { key: K; pending: number }[],
  requested: string | undefined,
): K | null {
  if (tabs.length === 0) return null;
  const explicit = tabs.find((t) => t.key === requested);
  if (explicit) return explicit.key;
  const firstPending = tabs.find((t) => t.pending > 0);
  return (firstPending ?? tabs[0]).key;
}
