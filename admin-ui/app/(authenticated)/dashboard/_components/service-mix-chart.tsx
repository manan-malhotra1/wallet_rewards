"use client";

/**
 * Transaction mix by service type — donut of counts. Answers "division of
 * transactions on service type".
 */
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { seriesColor } from "@/lib/chart-colors";
import type { ServiceSlice } from "@/lib/api-types";

export function ServiceMixChart({ data }: { data: ServiceSlice[] }) {
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
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="service_type"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={2}
            isAnimationActive={false}
          >
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
