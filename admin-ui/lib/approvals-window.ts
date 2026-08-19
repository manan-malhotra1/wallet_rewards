/**
 * Server-window helpers for the unified Approvals page (Story B7.1).
 *
 * The page no longer fetches full queues: the status facet and page number are
 * SERVER params (they change what window is fetched, via `?status=` / `?page=`),
 * while search/type/date stay client-side over the fetched window. These pure
 * helpers parse those URL params and map the backend `/counts` shape into the
 * toolbar's segment counts.
 */
import type { QueueCounts } from "./api-types";
import { STATUS_KEYS, type StatusKey } from "./approvals-filter";

/**
 * Rows fetched per page. Kept small — the load-tested queues hold thousands of
 * rows per status, and the backend still enriches money/user rows per-row
 * until B7.2 batches it, so page cost scales with this number. Backend `limit`
 * cap is 500.
 */
export const APPROVALS_PAGE_SIZE = 10;

/**
 * The status window the page lands on with no `?status=` param. PENDING,
 * because an approvals queue is an action list — the pending items are what a
 * checker came to do. Single source: the URL parser, the chip logic, and the
 * "omit the param when default" URL builder all read this constant.
 */
export const DEFAULT_SERVER_STATUS: StatusKey | "ALL" = "PENDING";

/**
 * Parse the `?status=` search param. Unknown or missing values fall back to
 * the default, so pre-B7.1 links keep their meaning. `"ALL"` means "no server
 * status filter".
 */
export function readServerStatus(raw: string | undefined): StatusKey | "ALL" {
  if (raw === "ALL") return "ALL";
  return (STATUS_KEYS as readonly string[]).includes(raw ?? "")
    ? (raw as StatusKey)
    : DEFAULT_SERVER_STATUS;
}

/**
 * The `status_filter` value to send to the backend list endpoints: the status
 * itself, or undefined for `"ALL"` (fetch every status). `StatusKey` is
 * value-identical to each queue's status union, so the result feeds all three
 * list clients directly.
 */
export function serverStatusParam(status: StatusKey | "ALL"): StatusKey | undefined {
  return status === "ALL" ? undefined : status;
}

/**
 * Parse the `?q=` search param. Since B7.2c the search runs SERVER-side across
 * the whole queue (the list and /counts endpoints take `q`), so this is a
 * server param exactly like status and page. Empty means "no search".
 */
export function readServerQ(raw: string | undefined): string {
  return raw?.trim() ?? "";
}

/** Parse the 1-based `?page=` param; anything but a positive integer means 1. */
export function readPage(raw: string | undefined): number {
  const page = Number(raw);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

/** Rows to skip for a 1-based page. */
export function windowOffset(page: number, pageSize: number): number {
  return (page - 1) * pageSize;
}

/**
 * Map a backend `QueueCounts` into the status segmented control's shape: every
 * lifecycle status (zero-filled defensively) plus `ALL` as the queue total.
 */
export function statusCountsWithAll(
  counts: QueueCounts,
): Record<StatusKey | "ALL", number> {
  const withAll = { ALL: counts.total } as Record<StatusKey | "ALL", number>;
  for (const status of STATUS_KEYS) {
    withAll[status] = counts.by_status[status] ?? 0;
  }
  return withAll;
}

/** Total pages for a row count — at least 1 so an empty queue still has a page. */
export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}
