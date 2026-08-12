/**
 * Pure, domain-generic filtering + counting for the unified Approvals page
 * toolbar (1a design). Every one of the three maker-checker queues (config
 * requests, money operations, user operations) is first normalised to an
 * `ApprovalRow` so this module never imports a domain type and stays trivially
 * unit-testable without React.
 *
 * The toolbar drives four independent facets — status, type, date range, and a
 * free-text search — over the active tab's rows. `summarize` composes them into
 * everything the UI renders: the per-status segmented counts, the filtered set,
 * and the "X of Y" line.
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

/** The four facet selections the toolbar owns. */
export interface ApprovalFilters {
  /** A specific `StatusKey`, or `"ALL"` for no status filter. */
  status: StatusKey | "ALL";
  /** Selected type codes — OR-matched; empty means "any type". */
  types: string[];
  /** Selected date-range preset. */
  dateRange: DateRangeKey;
  /** Free-text query; empty means "no search". */
  q: string;
}

/**
 * The neutral starting point. Status defaults to `PENDING` because an approvals
 * queue is an action list — the pending items are what a checker came to do —
 * and the date range defaults to `"all"` so a genuinely old pending request is
 * never hidden by an implicit window.
 */
export const DEFAULT_FILTERS: ApprovalFilters = {
  status: "PENDING",
  types: [],
  dateRange: "all",
  q: "",
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
 * Case-insensitive substring match of `q` across the row's request id, maker
 * (name + raw id), and summary/entity text. An empty/whitespace query matches
 * every row.
 */
export function matchesSearch(row: ApprovalRow, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  const haystack = `${row.id} ${row.maker} ${row.makerId} ${row.summary}`.toLowerCase();
  return haystack.includes(needle);
}

/**
 * Tally rows by lifecycle status. Always returns all four keys (zero-filled)
 * plus `ALL` (the total), so the status segmented control can render a count
 * next to every segment without post-processing.
 */
export function countByStatus(
  rows: ApprovalRow[],
): Record<StatusKey | "ALL", number> {
  const counts: Record<StatusKey | "ALL", number> = {
    PENDING: 0,
    CHANGES_REQUESTED: 0,
    APPLIED: 0,
    WITHDRAWN: 0,
    ALL: rows.length,
  };
  for (const row of rows) {
    if (row.status in counts && row.status !== "ALL") {
      counts[row.status as StatusKey] += 1;
    }
  }
  return counts;
}

/**
 * Apply every facet to `rows`. Type, date, and search always apply; status is
 * skipped when set to `"ALL"`. Pure — never mutates the input.
 *
 * @param rows Normalised rows for the active tab.
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
    if (!matchesSearch(row, filters.q)) return false;
    if (filters.status !== "ALL" && row.status !== filters.status) return false;
    return true;
  });
}

/**
 * Count rows awaiting a checker. Case-insensitive because the raw domain
 * statuses are lowercase while the toolbar normalises to uppercase.
 */
export function countPending(rows: { status: string }[]): number {
  return rows.filter((row) => row.status.toUpperCase() === "PENDING").length;
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

/** Everything the toolbar needs to render in one pass over the active rows. */
export interface ApprovalSummary {
  /** Rows passing every facet except status — the pool the segments count. */
  pool: ApprovalRow[];
  /** Rows passing every facet including status — what the table shows. */
  filtered: ApprovalRow[];
  /** Per-status counts of `pool`, so each segment's count reflects the other facets. */
  statusCounts: Record<StatusKey | "ALL", number>;
  /** `X` in "X of Y" — rows after all filters. */
  shown: number;
  /** `Y` in "X of Y" — total rows in the tab, before any filter. */
  total: number;
}

/**
 * Compose the facets into the toolbar's full view model. The status segmented
 * counts are computed over `pool` (rows matching every *other* facet), so each
 * segment shows how many rows selecting it would yield — standard faceted-search
 * behaviour that keeps the counts and the "X of Y" line mutually consistent.
 */
export function summarize(
  rows: ApprovalRow[],
  filters: ApprovalFilters,
  now: Date = new Date(),
): ApprovalSummary {
  const pool = applyFilters(rows, { ...filters, status: "ALL" }, now);
  const filtered =
    filters.status === "ALL"
      ? pool
      : pool.filter((row) => row.status === filters.status);
  return {
    pool,
    filtered,
    statusCounts: countByStatus(pool),
    shown: filtered.length,
    total: rows.length,
  };
}
