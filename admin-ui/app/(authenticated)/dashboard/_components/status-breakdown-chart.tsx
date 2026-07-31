"use client";

/**
 * Completed / failed / pending transactions per bucket (stacked bar).
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { STATUS_COLORS } from "@/lib/chart-colors";
import type { StatusBucket } from "@/lib/api-types";

export function StatusBreakdownChart({ data }: { data: StatusBucket[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No transactions yet.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Legend />
          <Bar dataKey="completed" stackId="s" fill={STATUS_COLORS.completed} isAnimationActive={false} />
          <Bar dataKey="failed" stackId="s" fill={STATUS_COLORS.failed} isAnimationActive={false} />
          <Bar dataKey="pending" stackId="s" fill={STATUS_COLORS.pending} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
