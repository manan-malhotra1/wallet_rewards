"use client";

/**
 * Shared scaffolding for the hand-drawn charts: gridlines, axis labels, hover
 * dots and the frosted tooltip.
 *
 * ## Why a fixed viewBox stretched horizontally
 *
 * Every chart draws into a {@link VB_WIDTH}-wide viewBox with
 * `preserveAspectRatio="none"` and an explicit pixel height, so the vertical
 * axis stays 1:1 with the viewBox while the horizontal axis stretches to the
 * panel. That removes the need to measure the container (no ResizeObserver, and
 * the chart is correct on first paint), at the cost of a horizontal scale
 * factor that would distort anything with a fixed aspect: strokes are kept even
 * with `vectorEffect="non-scaling-stroke"`, and text and hover dots live in an
 * HTML overlay rather than inside the SVG — which is also why the axis labels
 * here are spans, not `<text>`.
 */
import * as React from "react";

import type { GridLine, PlotRect, XTick } from "@/lib/chart-geometry";
import { cn } from "@/lib/utils";
import { Swatch } from "./indicators";

/** Every chart's viewBox width. Horizontal units are only ever relative. */
export const VB_WIDTH = 1000;

/** Convert a viewBox x into a CSS percentage for the HTML overlay. */
function pctX(x: number): string {
  return `${((x / VB_WIDTH) * 100).toFixed(3)}%`;
}

/**
 * Horizontal-only gridlines, drawn from the axis gutter to the right edge.
 *
 * No vertical lines and no axis rules: the x positions are already implied by
 * the labels, and a full lattice is the single biggest source of chart noise.
 */
export function GridLines({ lines, rect }: { lines: GridLine[]; rect: PlotRect }) {
  return (
    <g>
      {lines.map((line, i) => (
        <line
          key={i}
          x1={rect.x}
          x2={rect.x + rect.width}
          y1={line.y}
          y2={line.y}
          stroke="var(--grid)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </g>
  );
}

/**
 * Axis labels as an HTML overlay: y values in the left gutter, x buckets under
 * the plot. Non-interactive so it never eats the chart's hover events.
 */
export function AxisLabels({
  lines,
  ticks,
  formatValue,
  baselineY,
}: {
  lines: GridLine[];
  ticks: XTick[];
  /** Formats a gridline's domain value, e.g. abbreviate or prefix a symbol. */
  formatValue: (value: number) => string;
  /** y (in viewBox units == px) of the x-axis label row. */
  baselineY: number;
}) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {lines.map((line, i) => (
        <span
          key={`y${i}`}
          className="absolute left-0 -translate-y-1/2 text-[10px] leading-none whitespace-nowrap text-muted-foreground tabular-nums"
          style={{ top: line.y }}
        >
          {formatValue(line.value)}
        </span>
      ))}
      {ticks.map((tick, i) => (
        <span
          key={`x${i}`}
          className="absolute -translate-x-1/2 -translate-y-1/2 text-[10px] leading-none whitespace-nowrap text-muted-foreground tabular-nums"
          style={{ left: pctX(tick.x), top: baselineY }}
        >
          {tick.label}
        </span>
      ))}
    </div>
  );
}

/** One dot marking where a series crosses the hover cursor. */
export interface HoverDot {
  /** viewBox x. */
  x: number;
  /** viewBox y (== px, since the vertical scale is 1:1). */
  y: number;
  color: string;
}

/**
 * Hover markers as HTML circles.
 *
 * SVG `<circle>` would render as an ellipse under the horizontal stretch, so
 * these are absolutely positioned spans with a halo ring instead.
 */
export function HoverDots({ dots }: { dots: HoverDot[] }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      {dots.map((dot, i) => (
        <span
          key={i}
          className="absolute size-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-dot-halo"
          style={{ left: pctX(dot.x), top: dot.y }}
        >
          <span
            className="absolute top-1/2 left-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{ background: dot.color }}
          />
        </span>
      ))}
    </div>
  );
}

/** A row in the tooltip: a series and its value at the hovered bucket. */
export interface TooltipRow {
  label: string;
  value: string;
  color?: string;
  dashed?: boolean;
}

/**
 * The frosted hover tooltip.
 *
 * Flips to the left of the cursor once past ~60% of the plot so it can't be
 * clipped by the panel edge. `pointer-events: none` keeps it from stealing the
 * hover that spawned it.
 */
export function ChartTooltip({
  x,
  title,
  rows,
  flip,
}: {
  /** viewBox x of the hover cursor. */
  x: number;
  title: string;
  rows: TooltipRow[];
  flip: boolean;
}) {
  return (
    <div
      role="tooltip"
      className={cn(
        "glass-overlay pointer-events-none absolute top-4 z-[5] min-w-[168px] rounded-xl px-3.5 py-3",
        "shadow-[inset_0_1px_0_var(--hairline-top),0_18px_34px_-18px_rgba(0,0,0,0.6)]",
      )}
      style={{ left: `calc(${pctX(x)} ${flip ? "- 190px" : "+ 16px"})` }}
    >
      <div className="mb-2 text-[10.5px] font-medium tracking-[0.05em] text-muted-foreground uppercase">
        {title}
      </div>
      <div className="flex flex-col gap-1.5">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center justify-between gap-4.5">
            <div className="flex items-center gap-[7px] text-[11.5px] text-muted-foreground">
              <Swatch color={row.color} dashed={row.dashed} />
              {row.label}
            </div>
            <span className="text-[12.5px] font-semibold text-foreground tabular-nums">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Map a pointer event on a stretched SVG back to a viewBox x.
 *
 * The horizontal scale is `clientWidth / VB_WIDTH`, so the offset within the
 * element has to be divided back out before it can be compared against plot
 * coordinates.
 */
export function viewBoxX(event: React.MouseEvent<SVGSVGElement>): number {
  const box = event.currentTarget.getBoundingClientRect();
  if (box.width === 0) return 0;
  return ((event.clientX - box.left) / box.width) * VB_WIDTH;
}
