"use client";

/**
 * User distribution by user_type (donut).
 */
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { seriesColor } from "@/lib/chart-colors";
import type { UserTypeSlice } from "@/lib/api-types";

export function UserTypeChart({ data }: { data: UserTypeSlice[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No users yet.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="count" nameKey="user_type" innerRadius={55} outerRadius={85} paddingAngle={2}>
            {data.map((_, i) => (
              <Cell key={i} fill={seriesColor(i)} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
