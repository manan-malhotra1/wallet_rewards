"use client";

/**
 * Global range + granularity control for the dashboard. Segmented buttons;
 * changing either fires up to the dashboard client which refetches via the
 * server action and syncs URL params.
 */
import { cn } from "@/lib/utils";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

const RANGES: AnalyticsRange[] = ["24h", "7d", "30d", "quarter"];
const GRANULARITIES: AnalyticsGranularity[] = ["day", "week", "month"];

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
    <div className="flex items-center gap-3">
      <Segmented options={RANGES} value={range} onChange={onRangeChange} />
      <div className="h-4 w-px bg-border" />
      <Segmented options={GRANULARITIES} value={granularity} onChange={onGranularityChange} />
    </div>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border bg-card p-0.5">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
            opt === value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
