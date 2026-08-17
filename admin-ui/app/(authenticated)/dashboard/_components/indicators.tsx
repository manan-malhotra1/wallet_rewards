/**
 * Small repeated data indicators: delta pills, legend swatches, currency
 * badges and the horizontal share bars used by the breakdown panels.
 *
 * Every one of these pairs colour with a shape or a label — an arrow on a
 * delta, a dot or dash on a legend row — because the admin-UI accessibility
 * rule forbids conveying state with colour alone. Server-safe (no hooks).
 */
import * as React from "react";

import { cn } from "@/lib/utils";
import { formatDelta, percentDelta, type DeltaDirection } from "@/lib/analytics-format";

/** Arrow glyph paths, drawn inline so a delta never waits on an icon chunk. */
const ARROW = {
  up: "M12 19V6M6 12l6-6 6 6",
  down: "M12 5v13M6 12l6 6 6-6",
  flat: "M6 12h12",
} as const;

/**
 * Tinted surface + border + ink per direction.
 *
 * `color-mix()` against the semantic token keeps one source of truth for each
 * status colour — a hand-picked pair of tint hexes per scheme would need
 * re-picking the moment `--pos` moves.
 */
const TONE: Record<DeltaDirection, string> = {
  up: "text-pos bg-[color-mix(in_oklab,var(--pos)_14%,transparent)] border-[color-mix(in_oklab,var(--pos)_24%,transparent)]",
  down: "text-neg bg-[color-mix(in_oklab,var(--neg)_14%,transparent)] border-[color-mix(in_oklab,var(--neg)_24%,transparent)]",
  flat: "text-muted-foreground bg-chip border-border",
};

/**
 * A period-over-period change, as a tinted pill with a direction arrow.
 *
 * @param current - the current-period figure (API string decimal)
 * @param previous - the baseline figure; a zero baseline renders "—" flat,
 *   because a percentage against nothing is not a number the operator can act on
 * @param compact - the denser variant used inside per-currency tile rows
 * @param showBaseline - append a muted "vs prev" (omitted in compact rows,
 *   where the label would outweigh the figure)
 */
export function DeltaChip({
  current,
  previous,
  compact = false,
  showBaseline = false,
}: {
  current: string;
  previous: string;
  compact?: boolean;
  showBaseline?: boolean;
}) {
  const { label, direction } = formatDelta(percentDelta(current, previous));
  const size = compact ? "px-[7px] py-[3px] text-[10.5px]" : "px-2 py-1 text-[11.5px]";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[7px] border font-semibold",
        size,
        TONE[direction],
      )}
    >
      <svg
        width={compact ? 10 : 11}
        height={compact ? 10 : 11}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d={ARROW[direction]} />
      </svg>
      <span className="tabular-nums">{label}</span>
      {showBaseline ? <span className="font-medium text-muted-foreground">vs prev</span> : null}
    </span>
  );
}

/**
 * A legend marker: a colour chip for a solid series, a dash for a dotted one.
 *
 * The dashed variant mirrors how the previous-period overlay is actually
 * stroked, so the legend reads as a key to the chart rather than a colour list.
 */
export function Swatch({ color, dashed = false }: { color?: string; dashed?: boolean }) {
  if (dashed) {
    return (
      <span
        aria-hidden="true"
        className="inline-block w-3.5 border-t-[1.5px] border-dashed border-muted-foreground"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="inline-block size-2.5 shrink-0 rounded-[3px]"
      style={{ background: color }}
    />
  );
}

/** A legend row: swatch, label, then the caller's figures pushed right. */
export function LegendRow({
  color,
  dashed,
  label,
  children,
  className,
}: {
  color?: string;
  dashed?: boolean;
  label: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-[7px] text-[11.5px] text-muted-foreground", className)}>
      <Swatch color={color} dashed={dashed} />
      {label}
      {children}
    </div>
  );
}

/** A currency-code badge — a quiet chip, never a coloured pill. */
export function CodeChip({ code, className }: { code: string; className?: string }) {
  return (
    <span
      className={cn(
        "rounded-md border bg-chip px-[7px] py-[3px] text-[10px] font-semibold tracking-[0.08em] text-muted-foreground",
        className,
      )}
    >
      {code}
    </span>
  );
}

/**
 * A horizontal magnitude bar, scaled against the largest row in its group.
 *
 * Scaling to the group maximum rather than the total is deliberate: these
 * panels compare services against each other, and a share-of-total scale
 * squashes every row of a long tail into an invisible sliver.
 */
export function ShareBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="h-1.5 overflow-hidden rounded-[4px] bg-grid">
      <div
        className="h-full rounded-[4px] transition-[width] duration-200 ease-out"
        style={{ width: `${pct.toFixed(1)}%`, background: color }}
      />
    </div>
  );
}
