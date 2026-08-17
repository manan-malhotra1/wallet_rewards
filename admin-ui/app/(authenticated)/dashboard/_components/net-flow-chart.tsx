"use client";

/**
 * Wallet inflow vs outflow for a single currency, mirrored about a zero line.
 *
 * Money in grows up, money out grows down, both against the same scale — so a
 * range where the float is draining is visible as an asymmetric silhouette
 * rather than as two bars the reader has to subtract. The dashboard renders one
 * instance per selected currency; they are never combined.
 */
import * as React from "react";

import {
  bandCentres,
  bandTicks,
  barPath,
  niceMax,
  type GridLine,
  type PlotRect,
} from "@/lib/chart-geometry";
import { abbreviateNumber, formatBucketLabel } from "@/lib/analytics-format";
import { netFlowFor } from "@/lib/dashboard-series";
import type { AnalyticsGranularity, AnalyticsRange, NetFlowPoint } from "@/lib/api-types";
import { AxisLabels, GridLines, VB_WIDTH } from "./plot-frame";

const SVG_HEIGHT = 230;
const RECT: PlotRect = { x: 52, y: 12, width: VB_WIDTH - 60, height: 178 };
/** Half the plot for each direction; the zero line sits between them. */
const HALF = RECT.height / 2;
const ZERO_Y = RECT.y + HALF;
const AXIS_BASELINE = RECT.y + RECT.height + 20;
/** Widest a bar gets, however few buckets there are. */
const MAX_BAR = 16;

interface Props {
  data: NetFlowPoint[];
  currency: string;
  symbol: string;
  granularity: AnalyticsGranularity;
  range: AnalyticsRange;
}

export function NetFlowChart({ data, currency, symbol, granularity, range }: Props) {
  const points = React.useMemo(() => netFlowFor(data, currency), [data, currency]);

  const max = niceMax(
    Math.max(0, ...points.flatMap((point) => [point.inflow, point.outflow])),
  );
  const centres = bandCentres(points.length, RECT);
  const barWidth = points.length
    ? Math.min(MAX_BAR, (RECT.width / points.length) * 0.34)
    : MAX_BAR;

  // Four labelled lines: ±max and ±half, with zero drawn separately (stronger).
  const grid: GridLine[] = [
    { y: RECT.y, value: max },
    { y: RECT.y + HALF / 2, value: max / 2 },
    { y: ZERO_Y + HALF / 2, value: -max / 2 },
    { y: RECT.y + RECT.height, value: -max },
  ];

  const ticks = React.useMemo(
    () =>
      bandTicks(
        points.map((point) => formatBucketLabel(point.bucket, granularity, range)),
        RECT,
        6,
      ),
    [points, granularity, range],
  );

  if (points.length === 0) return null;

  return (
    <div className="relative mt-3.5 rounded-[14px] bg-surface-inset px-3 pt-3.5 pb-1.5 shadow-[inset_0_1px_0_var(--hairline-top)]">
      <svg
        viewBox={`0 0 ${VB_WIDTH} ${SVG_HEIGHT}`}
        preserveAspectRatio="none"
        className="block h-[230px] w-full"
        role="img"
        aria-label={`Wallet inflow versus outflow, ${currency}`}
      >
        <GridLines lines={grid} rect={RECT} />
        {points.map((point, i) => (
          <g key={point.bucket}>
            <path
              d={barPath(
                centres[i] - barWidth - 1.5,
                ZERO_Y,
                barWidth,
                (point.inflow / max) * HALF,
                3,
              )}
              fill="var(--chart-1)"
            />
            <path
              d={barPath(
                centres[i] + 1.5,
                ZERO_Y,
                barWidth,
                -(point.outflow / max) * HALF,
                3,
              )}
              fill="var(--chart-4)"
            />
          </g>
        ))}
        <line
          x1={RECT.x}
          x2={RECT.x + RECT.width}
          y1={ZERO_Y}
          y2={ZERO_Y}
          stroke="var(--zero-line)"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <AxisLabels
        lines={grid}
        ticks={ticks}
        formatValue={(value) =>
          `${value < 0 ? "−" : ""}${symbol}${abbreviateNumber(Math.abs(value))}`
        }
        baselineY={AXIS_BASELINE}
      />
    </div>
  );
}
