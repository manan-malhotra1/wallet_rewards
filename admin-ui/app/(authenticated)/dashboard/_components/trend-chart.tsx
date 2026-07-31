"use client";

/**
 * The shared main trend chart. Plots one metric (count or volume) over the
 * bucketed series with a dotted previous-period overlay — the visual
 * day-on-day / week-on-week comparison. Which metric shows is driven by the
 * selected stat tile.
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { TransactionsTimeseries } from "@/lib/api-types";

interface Props {
  data: TransactionsTimeseries;
  metric: "count" | "volume";
  label: string;
}

/** Merge current + previous into aligned rows keyed by bucket index. */
function toRows(data: TransactionsTimeseries, metric: "count" | "volume") {
  const len = Math.max(data.current.length, data.previous.length);
  return Array.from({ length: len }, (_, i) => ({
    bucket: data.current[i]?.bucket ?? data.previous[i]?.bucket ?? `${i}`,
    current: Number(data.current[i]?.[metric] ?? 0),
    previous: Number(data.previous[i]?.[metric] ?? 0),
  }));
}

export function TrendChart({ data, metric, label }: Props) {
  const rows = toRows(data, metric);
  if (rows.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        No activity in this range.
      </div>
    );
  }
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_SERIES[0]} stopOpacity={0.35} />
              <stop offset="100%" stopColor={CHART_SERIES[0]} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Area
            type="monotone"
            dataKey="current"
            name={label}
            stroke={CHART_SERIES[0]}
            fill="url(#trendFill)"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="previous"
            name="Previous period"
            stroke={CHART_SERIES[1]}
            strokeDasharray="4 4"
            strokeWidth={1.5}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
