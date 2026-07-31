"use client";

/**
 * Revenue by service type — stacked bar of fee / tax / commission.
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
import type { RevenueSlice } from "@/lib/api-types";

export function RevenueChart({ data }: { data: RevenueSlice[] }) {
  const rows = data.map((r) => ({
    service_type: r.service_type,
    fee: Number(r.fee),
    tax: Number(r.tax),
    commission: Number(r.commission),
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No revenue in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="service_type" fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Legend />
          <Bar dataKey="fee" stackId="r" fill={CHART_SERIES[0]} />
          <Bar dataKey="tax" stackId="r" fill={CHART_SERIES[3]} />
          <Bar dataKey="commission" stackId="r" fill={CHART_SERIES[2]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
