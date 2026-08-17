"use client";

/**
 * The shared chrome behind every Overview KPI tile.
 *
 * Both the count tile and the per-currency money tile need the same selected /
 * hover / focus behaviour, the same accent rail and the same bottom sparkline —
 * only the figures in the middle differ, so the shell lives here and the two
 * tiles supply their own body.
 *
 * Selection state is exposed through `aria-pressed` on a real `<button>`, so
 * keyboard activation and screen-reader state come from the element rather than
 * a hand-rolled `role`/`onKeyDown` pair. A non-selectable tile (New users, which
 * never drives the trend chart) renders as a plain `<div>` with no pointer
 * affordance, so its inertness is visible rather than surprising.
 */
import * as React from "react";

import { cn } from "@/lib/utils";
import { PANEL_ELEVATION } from "./panel";
import { Sparkline } from "./sparkline";

/** Lifted shadow while hovering a selectable tile. */
const HOVER_ELEVATION =
  "hover:shadow-[inset_0_1px_0_var(--hairline-top),0_20px_40px_-24px_rgba(0,0,0,0.6)]";

/** Deeper shadow for the charted tile, so selection reads as elevation too. */
const SELECTED_ELEVATION =
  "shadow-[inset_0_1px_0_var(--hairline-top),0_24px_48px_-24px_rgba(0,0,0,0.6)]";

export interface TileShellProps {
  /** Metric key reported back to the dashboard on selection. */
  id: string;
  /** Tile label, e.g. "Volume". */
  label: string;
  /** Whether this tile's metric is the one plotted in the trend chart. */
  selected: boolean;
  /** False for informational tiles that never drive the chart. */
  selectable?: boolean;
  onSelect: (id: string) => void;
  /** Series for the bottom sparkline; an empty array renders a blank strip. */
  spark: number[];
  /** Sparkline stroke/fill colour — a `--chart-n` token from chart-colors. */
  sparkColor: string;
  children: React.ReactNode;
}

export function TileShell({
  id,
  label,
  selected,
  selectable = true,
  onSelect,
  spark,
  sparkColor,
  children,
}: TileShellProps) {
  const shell = cn(
    "glass-panel relative flex min-h-[168px] flex-col overflow-hidden rounded-[14px] text-left",
    "transition-[transform,box-shadow,border-color,background-color] duration-[120ms] ease-out",
    selected ? SELECTED_ELEVATION : PANEL_ELEVATION,
    selected &&
      "border-primary-line bg-[linear-gradient(180deg,var(--primary-tint),transparent_60%)]",
    selectable
      ? cn(
          "cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
          !selected && cn("hover:-translate-y-0.5 hover:border-primary-line", HOVER_ELEVATION),
        )
      : "cursor-default",
  );

  const body = (
    <>
      {/* Accent rail: kept mounted and faded so selection doesn't reflow the tile. */}
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-x-0 top-0 h-[3px] bg-primary transition-opacity duration-150",
          selected ? "opacity-100" : "opacity-0",
        )}
      />
      <div className="relative px-[18px] pt-4">
        <div className="flex items-center justify-between gap-2.5">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          {selected ? (
            <span className="rounded-[5px] bg-primary-tint px-1.5 py-0.5 text-[9.5px] font-semibold tracking-[0.09em] text-primary uppercase">
              Charted
            </span>
          ) : null}
        </div>
        {children}
      </div>
      <Sparkline values={spark} color={sparkColor} />
    </>
  );

  if (!selectable) {
    return <div className={shell}>{body}</div>;
  }
  return (
    <button type="button" aria-pressed={selected} onClick={() => onSelect(id)} className={shell}>
      {body}
    </button>
  );
}
