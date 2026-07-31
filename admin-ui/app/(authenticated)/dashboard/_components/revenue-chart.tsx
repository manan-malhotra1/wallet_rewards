"use client";

/**
 * Revenue (operator fee) by service type, split by currency — one bar per
 * selected currency, never summed across currencies.
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

import { seriesColor } from "@/lib/chart-colors";
import type { CurrencyInfo, RevenueServiceSlice } from "@/lib/api-types";

interface Props {
  data: RevenueServiceSlice[];
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
}

export function RevenueChart({ data, selectedCurrencies, currencyMeta }: Props) {
  const currencies = selectedCurrencies.filter((c) => data.some((d) => d.currency === c));
  const byService = new Map<string, Record<string, number | string>>();
  for (const d of data) {
    if (!selectedCurrencies.includes(d.currency)) continue;
    const row = byService.get(d.service_type) ?? { service_type: d.service_type };
    row[d.currency] = Number(d.total);
    byService.set(d.service_type, row);
  }
  const rows = [...byService.values()];
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
          <YAxis fontSize={11} width={56} />
          <Tooltip />
          <Legend />
          {currencies.map((c, i) => (
            <Bar key={c} dataKey={c} name={currencyMeta[c]?.code ?? c} fill={seriesColor(i)} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
