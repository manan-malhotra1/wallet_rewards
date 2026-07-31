"use client";

/**
 * Shared trend chart. metric="count" → one agnostic area with dotted
 * previous-period overlay. metric="volume"|"revenue" → one solid line per
 * selected currency (never summed); the dotted previous overlay is shown only
 * when a single currency is selected, to avoid clutter.
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES, seriesColor } from "@/lib/chart-colors";
import type { CurrencyInfo, MetricsTimeseries } from "@/lib/api-types";

interface Props {
  data: MetricsTimeseries;
  metric: "count" | "volume" | "revenue";
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">{msg}</div>
  );
}

const fmtTick = (v: unknown) => String(v).slice(5, 10);

export function TrendChart({ data, metric, selectedCurrencies, currencyMeta }: Props) {
  if (metric === "count") {
    const cur = data.count.current;
    const prev = data.count.previous;
    const len = Math.max(cur.length, prev.length);
    const rows = Array.from({ length: len }, (_, i) => ({
      bucket: cur[i]?.bucket ?? prev[i]?.bucket ?? `${i}`,
      current: cur[i]?.count ?? 0,
      previous: prev[i]?.count ?? 0,
    }));
    if (rows.length === 0) return <Empty msg="No activity in this range." />;
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
            <XAxis dataKey="bucket" tickFormatter={fmtTick} fontSize={11} />
            <YAxis fontSize={11} width={48} />
            <Tooltip />
            <Area type="monotone" dataKey="current" name="Transactions" stroke={CHART_SERIES[0]} fill="url(#trendFill)" strokeWidth={2} isAnimationActive={false} />
            <Line type="monotone" dataKey="previous" name="Previous period" stroke={CHART_SERIES[1]} strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    );
  }

  const series = data[metric].filter((s) => selectedCurrencies.includes(s.currency));
  const len = series.reduce((m, s) => Math.max(m, s.current.length), 0);
  const baseBuckets = series[0]?.current ?? [];
  const single = series.length === 1;
  const rows = Array.from({ length: len }, (_, i) => {
    const row: Record<string, number | string> = { bucket: baseBuckets[i]?.bucket ?? `${i}` };
    for (const s of series) row[s.currency] = Number(s.current[i]?.value ?? 0);
    if (single) row.__prev = Number(series[0].previous[i]?.value ?? 0);
    return row;
  });
  if (rows.length === 0) return <Empty msg="No activity for the selected currencies." />;
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={fmtTick} fontSize={11} />
          <YAxis fontSize={11} width={56} />
          <Tooltip />
          {series.map((s, i) => (
            <Line
              key={s.currency}
              type="monotone"
              dataKey={s.currency}
              name={currencyMeta[s.currency]?.code ?? s.currency}
              stroke={seriesColor(i)}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          ))}
          {single ? (
            <Line type="monotone" dataKey="__prev" name="Previous period" stroke={CHART_SERIES[1]} strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          ) : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
