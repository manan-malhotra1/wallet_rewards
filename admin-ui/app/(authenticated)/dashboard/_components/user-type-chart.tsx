"use client";

/**
 * Share of the registered base by user type.
 *
 * A ranked bar list rather than a second donut: four categories with a dominant
 * first slice are easier to compare on a common baseline, and it keeps the only
 * ring on the page (service mix) meaningful.
 */
import { formatCount, sharePercent } from "@/lib/analytics-format";
import { seriesColor } from "@/lib/chart-colors";
import { userTypeLabel } from "@/lib/user-type-catalog";
import type { UserTypeCatalog, UserTypeSlice } from "@/lib/api-types";
import { ShareBar } from "./indicators";

/**
 * @param data One slice per user type, as returned by the analytics endpoint.
 * @param catalog The tenant's user-type catalog, so each row reads by the name
 *   the operator gave the type rather than by its raw code.
 */
export function UserTypeChart({
  data,
  catalog,
}: {
  data: UserTypeSlice[];
  catalog: UserTypeCatalog | null;
}) {
  const slices = [...data].filter((slice) => slice.count > 0).sort((a, b) => b.count - a.count);
  const total = slices.reduce((sum, slice) => sum + slice.count, 0);
  if (total === 0) return null;
  const max = slices[0].count;

  return (
    <div className="mt-3.5 flex flex-col gap-3.5 rounded-[14px] bg-surface-inset p-4 shadow-[inset_0_1px_0_var(--hairline-top)]">
      {slices.map((slice, i) => (
        <div key={slice.user_type} className="flex flex-col gap-[7px]">
          <div className="flex items-baseline gap-2.5">
            <span className="mr-auto text-xs text-foreground">
              {userTypeLabel(catalog, slice.user_type)}
            </span>
            <span className="text-[12.5px] font-semibold text-foreground tabular-nums">
              {formatCount(slice.count)}
            </span>
            <span className="min-w-[38px] text-right text-[10.5px] text-muted-foreground tabular-nums">
              {sharePercent(slice.count, total)}
            </span>
          </div>
          <ShareBar value={slice.count} max={max} color={seriesColor(i)} />
        </div>
      ))}
    </div>
  );
}
