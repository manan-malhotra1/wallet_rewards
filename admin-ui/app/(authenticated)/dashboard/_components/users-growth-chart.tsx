"use client";

/**
 * New registrations per bucket (bar) with a dotted previous-period line.
 */
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { UsersTimeseries } from "@/lib/api-types";

export function UsersGrowthChart({ data }: { data: UsersTimeseries }) {
  const len = Math.max(data.current.length, data.previous.length);
  const rows = Array.from({ length: len }, (_, i) => ({
    bucket: data.current[i]?.bucket ?? data.previous[i]?.bucket ?? `${i}`,
    current: data.current[i]?.count ?? 0,
    previous: data.previous[i]?.count ?? 0,
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No new registrations in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Bar dataKey="current" name="New users" fill={CHART_SERIES[0]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Line
            type="monotone"
            dataKey="previous"
            name="Previous period"
            stroke={CHART_SERIES[1]}
            strokeDasharray="4 4"
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
