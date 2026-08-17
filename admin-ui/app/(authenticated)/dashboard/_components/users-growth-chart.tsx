"use client";

/**
 * New registrations across the range — a single gradient-filled area.
 *
 * Deliberately quieter than the hero chart (three gridlines, five ticks, no
 * hover tooltip): it sits in a half-width panel where a full instrument would
 * crowd out the figures beside it.
 */
import * as React from "react";

import {
  areaPath,
  gridLines,
  niceMax,
  smoothPath,
  xTicks,
  type PlotRect,
} from "@/lib/chart-geometry";
import { abbreviateNumber, formatBucketLabel } from "@/lib/analytics-format";
import { registrationLabels, registrationValues } from "@/lib/dashboard-series";
import type { AnalyticsGranularity, AnalyticsRange, UsersTimeseries } from "@/lib/api-types";
import { AxisLabels, GridLines, VB_WIDTH } from "./plot-frame";

const SVG_HEIGHT = 210;
const RECT: PlotRect = { x: 46, y: 8, width: VB_WIDTH - 54, height: 162 };
const AXIS_BASELINE = RECT.y + RECT.height + 20;

interface Props {
  data: UsersTimeseries;
  granularity: AnalyticsGranularity;
  range: AnalyticsRange;
}

export function UsersGrowthChart({ data, granularity, range }: Props) {
  const values = registrationValues(data);
  const labels = registrationLabels(data);
  const max = niceMax(Math.max(0, ...values) * 1.1);

  const grid = React.useMemo(() => gridLines(max, RECT, 3), [max]);
  const ticks = React.useMemo(
    () => xTicks(labels.map((b) => formatBucketLabel(b, granularity, range)), RECT, 5),
    [labels, granularity, range],
  );

  if (values.length === 0) return null;
  const line = smoothPath(values, RECT, max);

  return (
    <div className="relative mt-3.5 rounded-[14px] bg-surface-inset px-3 pt-3.5 pb-1.5 shadow-[inset_0_1px_0_var(--hairline-top)]">
      <svg
        viewBox={`0 0 ${VB_WIDTH} ${SVG_HEIGHT}`}
        preserveAspectRatio="none"
        className="block h-[210px] w-full"
        role="img"
        aria-label="New registrations over time"
      >
        <defs>
          <linearGradient id="registrations-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-3)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--chart-3)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <GridLines lines={grid} rect={RECT} />
        <path d={areaPath(line, RECT)} fill="url(#registrations-fill)" />
        <path
          d={line}
          fill="none"
          stroke="var(--chart-3)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <AxisLabels
        lines={grid}
        ticks={ticks}
        formatValue={abbreviateNumber}
        baselineY={AXIS_BASELINE}
      />
    </div>
  );
}
