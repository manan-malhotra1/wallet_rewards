"use client";

/**
 * Transaction mix by service type — a donut whose hole carries the range total.
 *
 * The ring answers "what's the shape of our traffic" and the centre answers
 * "out of how many", so the two together replace the figure that would
 * otherwise need a separate tile. The legend doubles as the value table
 * (count + share), which is why the ring itself needs no labels or callouts.
 */
import { ringPath } from "@/lib/chart-geometry";
import { abbreviateNumber, formatCount, sharePercent } from "@/lib/analytics-format";
import { seriesColor } from "@/lib/chart-colors";
import { serviceLabel } from "@/lib/service-label";
import type { ServiceSlice } from "@/lib/api-types";
import { Swatch } from "./indicators";

/** Donut geometry: a square SVG, so no aspect-ratio stretching here. */
const SIZE = 188;
const CENTRE = SIZE / 2;
const OUTER = 86;
const INNER = 60;
/** Angular gap between slices, in degrees, so neighbours read as separate. */
const GAP = 1.2;

export function ServiceMixChart({ data }: { data: ServiceSlice[] }) {
  const slices = data.filter((slice) => slice.count > 0);
  const total = slices.reduce((sum, slice) => sum + slice.count, 0);
  if (total === 0) return null;

  // Each slice's start angle is a prefix sum rather than a running accumulator:
  // mutating a captured variable inside a render-time map is what the React
  // Compiler lint rule rejects, and the slice count here is single digits.
  const arcs = slices.map((slice, i) => {
    const preceding = slices.slice(0, i).reduce((sum, s) => sum + s.count, 0);
    const start = (preceding / total) * 360;
    const span = (slice.count / total) * 360;
    return {
      key: slice.service_type,
      path: ringPath(CENTRE, CENTRE, OUTER, INNER, start + GAP, start + span - GAP),
      color: seriesColor(i),
    };
  });

  return (
    <div className="mt-3.5 flex flex-wrap items-center gap-5.5 rounded-[14px] bg-surface-inset p-3.5 shadow-[inset_0_1px_0_var(--hairline-top)]">
      <div className="relative size-[188px] shrink-0">
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden="true">
          {arcs.map((arc) => (
            <path key={arc.key} d={arc.path} fill={arc.color} />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
          <span className="text-[25px] font-semibold tracking-[-0.02em] text-foreground tabular-nums">
            {abbreviateNumber(total)}
          </span>
          <span className="text-[10.5px] text-muted-foreground">transactions</span>
        </div>
      </div>

      <ul className="flex min-w-[180px] flex-1 basis-[190px] flex-col gap-1.5">
        {slices.map((slice, i) => (
          <li
            key={slice.service_type}
            className="flex items-center gap-2.5 rounded-[9px] border bg-chip px-2.5 py-1.5"
          >
            <Swatch color={seriesColor(i)} />
            <span className="mr-auto text-[11.5px] text-foreground">
              {serviceLabel(slice.service_type)}
            </span>
            <span className="text-[11.5px] font-semibold text-foreground tabular-nums">
              {formatCount(slice.count)}
            </span>
            <span className="min-w-[38px] text-right text-[10.5px] text-muted-foreground tabular-nums">
              {sharePercent(slice.count, total)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
