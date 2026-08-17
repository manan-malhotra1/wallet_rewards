"use client";

/**
 * Global range + granularity control for the dashboard.
 *
 * Both segments share one inset track with a hairline divider between them, so
 * they read as a single "what window am I looking at" control rather than two
 * unrelated widgets. Changing either fires up to the dashboard client, which
 * refetches via the server action and syncs the URL params.
 */
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";
import { SegmentedControl } from "./segmented-control";

const RANGES: readonly AnalyticsRange[] = ["24h", "7d", "30d", "quarter"];
const GRANULARITIES: readonly AnalyticsGranularity[] = ["day", "week", "month"];

interface Props {
  range: AnalyticsRange;
  granularity: AnalyticsGranularity;
  onRangeChange: (r: AnalyticsRange) => void;
  onGranularityChange: (g: AnalyticsGranularity) => void;
}

export function TimeRangeSwitcher({
  range,
  granularity,
  onRangeChange,
  onGranularityChange,
}: Props) {
  return (
    <div className="flex items-center gap-0 rounded-xl border bg-surface-inset p-[3px] shadow-[inset_0_1px_0_var(--hairline-top)]">
      <SegmentedControl
        options={RANGES}
        value={range}
        onChange={onRangeChange}
        label="Time range"
      />
      <span aria-hidden="true" className="mx-1.5 my-1 w-px self-stretch bg-border" />
      <SegmentedControl
        options={GRANULARITIES}
        value={granularity}
        onChange={onGranularityChange}
        label="Granularity"
      />
    </div>
  );
}
