"use client";

/**
 * Points issued vs redeemed per bucket (dual line).
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { RewardsTimeseries } from "@/lib/api-types";

export function RewardsChart({ data }: { data: RewardsTimeseries }) {
  const rows = data.points.map((p) => ({
    bucket: p.bucket,
    issued: Number(p.issued),
    redeemed: Number(p.redeemed),
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No rewards activity in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Line type="monotone" dataKey="issued" name="Issued" stroke={CHART_SERIES[4]} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="redeemed" name="Redeemed" stroke={CHART_SERIES[2]} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
