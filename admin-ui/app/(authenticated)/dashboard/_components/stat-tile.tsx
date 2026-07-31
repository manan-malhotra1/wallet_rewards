"use client";

/**
 * A clickable KPI stat tile: big value + a delta chip vs the previous period.
 * Selecting it tells the dashboard which metric to plot in the shared trend
 * chart. Colour is always paired with an arrow/icon (never colour alone).
 */
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDelta, percentDelta } from "@/lib/analytics-format";

interface Props {
  id: string;
  label: string;
  value: string;
  current: string;
  previous: string;
  selected: boolean;
  onSelect: (id: string) => void;
}

export function StatTile({ id, label, value, current, previous, selected, onSelect }: Props) {
  const { label: deltaLabel, direction } = formatDelta(percentDelta(current, previous));
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  const tone =
    direction === "up"
      ? "text-emerald-600 dark:text-emerald-400"
      : direction === "down"
        ? "text-red-600 dark:text-red-400"
        : "text-muted-foreground";

  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-start gap-1 rounded-lg border bg-card p-4 text-left transition-colors",
        selected ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
      )}
    >
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-2xl font-bold tabular-nums text-foreground">{value}</span>
      <span className={cn("inline-flex items-center gap-1 text-xs font-semibold", tone)}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {deltaLabel}
        <span className="font-normal text-muted-foreground">vs prev</span>
      </span>
    </button>
  );
}
