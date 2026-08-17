"use client";

/**
 * Completed / pending / failed share of the range, as one stacked bar.
 *
 * Rolled up rather than plotted per bucket: the operator question here is "what
 * proportion of this range settled", and a stacked time series answers it worse
 * than a single proportion plus exact counts.
 *
 * Each status carries an icon as well as its colour, so the breakdown is still
 * readable without colour vision — the admin-UI rule that status colour is
 * never load-bearing on its own.
 */
import { formatCount, sharePercent } from "@/lib/analytics-format";
import { statusTotals } from "@/lib/dashboard-series";
import type { StatusBucket } from "@/lib/api-types";

/** Icon paths drawn inline (a tick, a clock, a cross). */
const STATUS = [
  { key: "completed", label: "Completed", color: "var(--pos)", icon: "M20 6L9 17l-5-5" },
  {
    key: "pending",
    label: "Pending",
    color: "var(--warn)",
    icon: "M12 7v5l3 2M12 3a9 9 0 100 18 9 9 0 000-18z",
  },
  { key: "failed", label: "Failed", color: "var(--neg)", icon: "M18 6L6 18M6 6l12 12" },
] as const;

export function StatusBreakdownChart({ data }: { data: StatusBucket[] }) {
  const totals = statusTotals(data);
  if (totals.total === 0) return null;

  const rows = STATUS.map((status) => ({
    ...status,
    value: totals[status.key],
    share: (totals[status.key] / totals.total) * 100,
  }));

  return (
    <div className="mt-4 rounded-[14px] bg-surface-inset p-4 shadow-[inset_0_1px_0_var(--hairline-top)]">
      <div className="flex h-[34px] overflow-hidden rounded-[9px] bg-grid">
        {rows
          .filter((row) => row.value > 0)
          .map((row, i, visible) => (
            <div
              key={row.key}
              title={`${row.label} ${row.share.toFixed(1)}%`}
              style={{
                width: `${row.share.toFixed(2)}%`,
                background: row.color,
                minWidth: 3,
                // Hairline separators cut in the panel's own tint, so adjacent
                // segments stay distinct even when one is a sliver.
                borderRight: i < visible.length - 1 ? "1.5px solid var(--glass-atmosphere-base)" : undefined,
              }}
            />
          ))}
      </div>

      <div className="mt-3.5 flex flex-col gap-0.5">
        {rows.map((row, i) => (
          <div
            key={row.key}
            className={`flex items-center gap-2.5 py-2.5 ${i === 0 ? "" : "border-t"}`}
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke={row.color}
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d={row.icon} />
            </svg>
            <span className="mr-auto text-xs text-foreground">{row.label}</span>
            <span className="text-[12.5px] font-semibold text-foreground tabular-nums">
              {formatCount(row.value)}
            </span>
            <span
              className="min-w-[52px] rounded-[5px] px-1.5 py-0.5 text-right text-[10.5px] tabular-nums"
              style={{
                color: row.color,
                background: `color-mix(in oklab, ${row.color} 14%, transparent)`,
              }}
            >
              {sharePercent(row.value, totals.total)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
