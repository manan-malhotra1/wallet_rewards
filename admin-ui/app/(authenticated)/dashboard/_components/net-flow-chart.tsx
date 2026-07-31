"use client";

/**
 * Inflow vs outflow into user wallets for a single currency (grouped bars).
 * The dashboard renders one instance per selected currency.
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

import { CHART_SERIES } from "@/lib/chart-colors";
import type { NetFlowPoint } from "@/lib/api-types";

export function NetFlowChart({ data, currency }: { data: NetFlowPoint[]; currency: string }) {
  const rows = data
    .filter((p) => p.currency === currency)
    .map((p) => ({ bucket: p.bucket, inflow: Number(p.inflow), outflow: Number(p.outflow) }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
        No wallet movement.
      </div>
    );
  }
  return (
    <div className="h-[200px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={56} />
          <Tooltip />
          <Legend />
          <Bar dataKey="inflow" fill={CHART_SERIES[4]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="outflow" fill={CHART_SERIES[5]} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
