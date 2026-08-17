"use client";

/**
 * The trend strip along the bottom of a KPI tile.
 *
 * Deliberately unlabelled — no axes, ticks or dots. It answers "which way is
 * this going" at a glance; the panel below answers "by how much". Drawn against
 * a fixed viewBox and stretched with `preserveAspectRatio="none"` so it fills
 * any tile width without measuring the DOM; `vectorEffect="non-scaling-stroke"`
 * keeps the stroke an even weight once that stretch is applied.
 */
import * as React from "react";

import { areaPath, smoothPath, type PlotRect } from "@/lib/chart-geometry";

/** Fixed drawing space. Only the ratio matters — the SVG scales to its tile. */
const RECT: PlotRect = { x: 0, y: 2, width: 320, height: 36 };

export function Sparkline({ values, color }: { values: number[]; color: string }) {
  const gradientId = `spark-${React.useId()}`;
  if (values.length === 0) return <div className="h-10" aria-hidden="true" />;

  // Pad the domain so the curve never touches the tile edges: a series that
  // grazes the top of its box reads as clipped rather than as a peak.
  const peak = Math.max(...values);
  const trough = Math.min(...values);
  const max = peak > 0 ? peak * 1.12 : 1;
  const min = trough > 0 ? trough * 0.9 : 0;

  const line = smoothPath(values, RECT, max, min);

  return (
    <svg
      viewBox="0 0 320 40"
      preserveAspectRatio="none"
      className="mt-auto block h-10 w-full"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath(line, RECT)} fill={`url(#${gradientId})`} />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
