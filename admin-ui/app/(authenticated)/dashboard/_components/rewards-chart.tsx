"use client";

/**
 * Points issued vs redeemed per bucket, as paired bars on a shared baseline.
 *
 * Both series grow upward here (unlike net flow): issuing and redeeming are not
 * opposite directions of one balance, they are two independent flows whose gap
 * is the outstanding liability — and a gap is easier to read side by side than
 * mirrored.
 *
 * Points are unitless, so no currency symbol appears anywhere in this panel.
 */
import * as React from "react";

import {
  bandCentres,
  bandTicks,
  barPath,
  gridLines,
  niceMax,
  type PlotRect,
} from "@/lib/chart-geometry";
import { abbreviateNumber, formatBucketLabel } from "@/lib/analytics-format";
import { rewardsFlow } from "@/lib/dashboard-series";
import type { AnalyticsGranularity, AnalyticsRange, RewardsTimeseries } from "@/lib/api-types";
import { AxisLabels, GridLines, VB_WIDTH } from "./plot-frame";

const SVG_HEIGHT = 230;
const RECT: PlotRect = { x: 46, y: 12, width: VB_WIDTH - 54, height: 178 };
const AXIS_BASELINE = RECT.y + RECT.height + 20;
const MAX_BAR = 15;

interface Props {
  data: RewardsTimeseries;
  granularity: AnalyticsGranularity;
  range: AnalyticsRange;
}

export function RewardsChart({ data, granularity, range }: Props) {
  const points = React.useMemo(() => rewardsFlow(data), [data]);

  const max = niceMax(Math.max(0, ...points.flatMap((p) => [p.issued, p.redeemed])));
  const centres = bandCentres(points.length, RECT);
  const barWidth = points.length
    ? Math.min(MAX_BAR, (RECT.width / points.length) * 0.34)
    : MAX_BAR;
  const baseline = RECT.y + RECT.height;

  const grid = React.useMemo(() => gridLines(max, RECT, 3), [max]);
  const ticks = React.useMemo(
    () =>
      bandTicks(
        points.map((point) => formatBucketLabel(point.bucket, granularity, range)),
        RECT,
        5,
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
        aria-label="Points issued versus redeemed"
      >
        <GridLines lines={grid} rect={RECT} />
        {points.map((point, i) => (
          <g key={point.bucket}>
            <path
              d={barPath(
                centres[i] - barWidth - 1.5,
                baseline,
                barWidth,
                (point.issued / max) * RECT.height,
                3,
              )}
              fill="var(--chart-1)"
            />
            <path
              d={barPath(
                centres[i] + 1.5,
                baseline,
                barWidth,
                (point.redeemed / max) * RECT.height,
                3,
              )}
              fill="var(--chart-5)"
            />
          </g>
        ))}
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
