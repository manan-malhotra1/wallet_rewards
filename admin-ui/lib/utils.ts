/**
 * Tiny utility helpers used across the admin UI.
 *
 * `cn` is the classic `clsx` + `tailwind-merge` combo — it lets components
 * accept caller-provided className strings without breaking the cascade of
 * variants from `class-variance-authority`.
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Conditionally join class names and resolve Tailwind conflicts. The last
 * conflicting utility wins (e.g. `bg-white bg-red-500` → `bg-red-500`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a Decimal-like string or number as a financial amount.
 * - Adds thousands separators.
 * - 2 fraction digits for money, 0 for points.
 * - Tabular-nums-friendly output (raw string; component wraps in monospace).
 */
export function formatAmount(
  value: string | number,
  options: { fractionDigits?: number } = {},
): string {
  const num = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(num)) return String(value);
  const digits = options.fractionDigits ?? 2;
  return num.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * Format an ISO timestamp as `MMM dd HH:mm` (e.g. `Apr 28 09:14`).
 * Short enough for dense tables; long enough to disambiguate weeks.
 */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Truncate a UUID-ish identifier for display: `usr_7a3f8c…` style.
 * Keeps the last 6 chars + an ellipsis. We hash-strip dashes so UUIDs and
 * opaque tokens both surface readably.
 */
export function shortId(id: string, prefix?: string): string {
  if (!id) return "";
  const compact = id.replace(/-/g, "");
  const tail = compact.slice(0, 8);
  return prefix ? `${prefix}_${tail}…` : `${tail}…`;
}
