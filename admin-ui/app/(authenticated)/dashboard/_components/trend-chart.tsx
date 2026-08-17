"use client";

/**
 * The dashboard's hero chart: the selected KPI plotted over the range.
 *
 * `metric="count"` draws one currency-agnostic area; `volume`/`revenue` draw one
 * line per selected currency, never summed. A dotted previous-period overlay is
 * shown whenever there is exactly one series to compare against.
 *
 * Hover is index-based rather than per-point hit-testing: the pointer's x maps
 * to the nearest bucket, which then drives the cursor line, every series' dot
 * and the tooltip together — so the reading is always internally consistent.
 */
import * as React from "react";

import {
  areaPath,
  gridLines,
  nearestIndex,
  niceMax,
  smoothPath,
  xAt,
  xTicks,
  type PlotRect,
} from "@/lib/chart-geometry";
import {
  abbreviateNumber,
  formatBucketLabel,
  formatCount,
} from "@/lib/analytics-format";
import { seriesColor } from "@/lib/chart-colors";
import { buildTrendData, type TrendMetric } from "@/lib/dashboard-series";
import type {
  AnalyticsGranularity,
  AnalyticsRange,
  CurrencyInfo,
  MetricsTimeseries,
} from "@/lib/api-types";
import {
  AxisLabels,
  ChartTooltip,
  GridLines,
  HoverDots,
  VB_WIDTH,
  viewBoxX,
} from "./plot-frame";

/** Plot geometry. Height is fixed in px so the vertical scale stays 1:1. */
const SVG_HEIGHT = 300;
const RECT: PlotRect = { x: 52, y: 8, width: VB_WIDTH - 60, height: 250 };
const AXIS_BASELINE = RECT.y + RECT.height + 22;

interface Props {
  data: MetricsTimeseries;
  metric: TrendMetric;
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
  granularity: AnalyticsGranularity;
  range: AnalyticsRange;
}

export function TrendChart({
  data,
  metric,
  selectedCurrencies,
  currencyMeta,
  granularity,
  range,
}: Props) {
  const [hover, setHover] = React.useState<number | null>(null);

  const symbols = React.useMemo(
    () =>
      Object.fromEntries(Object.values(currencyMeta).map((c) => [c.code, c.symbol])) as Record<
        string,
        string
      >,
    [currencyMeta],
  );

  const trend = React.useMemo(
    () => buildTrendData(data, metric, selectedCurrencies, symbols),
    [data, metric, selectedCurrencies, symbols],
  );

  const { labels, series, previous } = trend;
  const count = labels.length;

  // Domain spans every visible series plus the overlay, so the dotted previous
  // period can't run off the top of the plot.
  const peak = React.useMemo(() => {
    const values = series.flatMap((s) => s.values).concat(previous ?? []);
    return values.length ? Math.max(...values) : 0;
  }, [series, previous]);
  const max = niceMax(peak * 1.08);

  const grid = React.useMemo(() => gridLines(max, RECT, 4), [max]);
  const ticks = React.useMemo(
    () => xTicks(labels.map((b) => formatBucketLabel(b, granularity, range)), RECT, 8),
    [labels, granularity, range],
  );

  if (count === 0) return null;

  // A single currency's symbol can label the y axis; a mixed set cannot, so the
  // axis stays unitless and the tooltip carries the symbols instead.
  const axisSymbol = series.length === 1 ? series[0].symbol : "";
  const formatAxis = (value: number) => `${axisSymbol}${abbreviateNumber(value)}`;
  const formatValue = (value: number, symbol: string) =>
    symbol ? `${symbol} ${formatCount(value)}` : formatCount(value);

  const hoverX = hover === null ? 0 : xAt(hover, count, RECT);
  const isArea = metric === "count";

  return (
    <div className="relative rounded-[14px] bg-surface-inset px-3.5 pt-4 pb-2 shadow-[inset_0_1px_0_var(--hairline-top)]">
      <svg
        viewBox={`0 0 ${VB_WIDTH} ${SVG_HEIGHT}`}
        preserveAspectRatio="none"
        className="block h-[300px] w-full touch-none"
        onMouseMove={(event) => {
          const next = nearestIndex(viewBoxX(event), count, RECT);
          if (next !== hover) setHover(next);
        }}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`${series.map((s) => s.label).join(", ")} over time`}
      >
        <defs>
          {series.map((s, i) => (
            <linearGradient key={s.key} id={`trend-fill-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={seriesColor(i)} stopOpacity="0.3" />
              <stop offset="100%" stopColor={seriesColor(i)} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>

        <GridLines lines={grid} rect={RECT} />

        {previous ? (
          <path
            d={smoothPath(previous, RECT, max)}
            fill="none"
            stroke="var(--muted-foreground)"
            strokeWidth="1.4"
            strokeDasharray="3 4"
            strokeLinecap="round"
            opacity="0.75"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}

        {series.map((s, i) => {
          const line = smoothPath(s.values, RECT, max);
          return (
            <g key={s.key}>
              {isArea ? <path d={areaPath(line, RECT)} fill={`url(#trend-fill-${s.key})`} /> : null}
              <path
                d={line}
                fill="none"
                stroke={seriesColor(i)}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}

        {hover !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={RECT.y}
            y2={RECT.y + RECT.height}
            stroke="var(--primary)"
            strokeWidth="1"
            opacity="0.5"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>

      <AxisLabels
        lines={grid}
        ticks={ticks}
        formatValue={formatAxis}
        baselineY={AXIS_BASELINE}
      />

      {hover !== null ? (
        <>
          <HoverDots
            dots={series.map((s, i) => ({
              x: hoverX,
              y:
                RECT.y +
                RECT.height -
                ((s.values[hover] ?? 0) / max) * RECT.height,
              color: seriesColor(i),
            }))}
          />
          <ChartTooltip
            x={hoverX}
            flip={(hoverX - RECT.x) / RECT.width > 0.6}
            title={formatBucketLabel(labels[hover], granularity, range)}
            rows={[
              ...series.map((s, i) => ({
                label: s.label,
                value: formatValue(s.values[hover] ?? 0, s.symbol),
                color: seriesColor(i),
              })),
              ...(previous
                ? [
                    {
                      label: "Previous",
                      value: formatValue(previous[hover] ?? 0, series[0]?.symbol ?? ""),
                      dashed: true,
                    },
                  ]
                : []),
            ]}
          />
        </>
      ) : null}
    </div>
  );
}

/** The chart's legend, rendered in the panel header beside the title. */
export function TrendLegend({
  data,
  metric,
  selectedCurrencies,
}: Pick<Props, "data" | "metric" | "selectedCurrencies">) {
  const { series, previous } = buildTrendData(data, metric, selectedCurrencies);
  return (
    <div className="flex flex-wrap items-center gap-3.5">
      {series.map((s, i) => (
        <div
          key={s.key}
          className="flex items-center gap-[7px] text-[11.5px] text-muted-foreground"
        >
          <span
            aria-hidden="true"
            className="inline-block size-2.5 rounded-[3px]"
            style={{ background: seriesColor(i) }}
          />
          {s.label}
        </div>
      ))}
      {previous ? (
        <div className="flex items-center gap-[7px] text-[11.5px] text-muted-foreground">
          <span
            aria-hidden="true"
            className="inline-block w-3.5 border-t-[1.5px] border-dashed border-muted-foreground"
          />
          Previous period
        </div>
      ) : null}
    </div>
  );
}
