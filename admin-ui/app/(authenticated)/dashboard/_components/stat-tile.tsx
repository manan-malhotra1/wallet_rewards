"use client";

/**
 * A currency-agnostic KPI tile: one big count, a delta pill vs the previous
 * period, and a sparkline of the same metric across the selected range.
 *
 * Selecting it tells the dashboard which metric the shared trend chart plots.
 * Direction is always carried by an arrow as well as colour (see DeltaChip).
 */
import { CHART_SERIES } from "@/lib/chart-colors";
import { DeltaChip } from "./indicators";
import { TileShell } from "./metric-tile-shell";

interface Props {
  id: string;
  label: string;
  /** Pre-formatted display figure (grouped, never raw). */
  value: string;
  current: string;
  previous: string;
  /** Unit suffix beside the figure, e.g. "txns" / "users". */
  unit?: string;
  /** Series for the tile sparkline, oldest bucket first. */
  spark?: number[];
  /** Sparkline colour; defaults to the primary series token. */
  sparkColor?: string;
  selected: boolean;
  /** False for informational tiles that never drive the trend chart. */
  selectable?: boolean;
  onSelect: (id: string) => void;
}

export function StatTile({
  id,
  label,
  value,
  current,
  previous,
  unit,
  spark = [],
  sparkColor = CHART_SERIES[0],
  selected,
  selectable = true,
  onSelect,
}: Props) {
  return (
    <TileShell
      id={id}
      label={label}
      selected={selected}
      selectable={selectable}
      onSelect={onSelect}
      spark={spark}
      sparkColor={sparkColor}
    >
      <div className="mt-2.5 flex items-end justify-between gap-3">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[30px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular-nums">
            {value}
          </span>
          {unit ? <span className="text-xs text-muted-foreground">{unit}</span> : null}
        </div>
        <DeltaChip current={current} previous={previous} showBaseline />
      </div>
      <div className="h-3.5" />
    </TileShell>
  );
}
