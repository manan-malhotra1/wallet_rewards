"use client";

/**
 * A money KPI tile that lists one line per selected currency — values are
 * never summed across currencies. Clicking selects this metric for the shared
 * trend chart. Reuses percentDelta/formatDelta for each currency's chip.
 */
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDelta, percentDelta } from "@/lib/analytics-format";
import type { CurrencyInfo, CurrencyScalar } from "@/lib/api-types";

interface Props {
  id: string;
  label: string;
  data: CurrencyScalar[];
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
  selected: boolean;
  onSelect: (id: string) => void;
}

export function MoneyStatTile({ id, label, data, selectedCurrencies, currencyMeta, selected, onSelect }: Props) {
  const rows = selectedCurrencies
    .map((code) => data.find((d) => d.currency === code))
    .filter((d): d is CurrencyScalar => Boolean(d));

  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-start gap-1.5 rounded-lg border bg-card p-4 text-left transition-colors",
        selected ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
      )}
    >
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {rows.length === 0 ? (
        <span className="text-2xl font-bold tabular-nums text-foreground">—</span>
      ) : (
        rows.map((r) => {
          const { label: deltaLabel, direction } = formatDelta(percentDelta(r.current, r.previous));
          const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
          const tone =
            direction === "up"
              ? "text-emerald-600 dark:text-emerald-400"
              : direction === "down"
                ? "text-red-600 dark:text-red-400"
                : "text-muted-foreground";
          const meta = currencyMeta[r.currency];
          return (
            <div key={r.currency} className="flex w-full items-baseline justify-between gap-2">
              <span className="text-lg font-bold tabular-nums text-foreground">
                <span className="mr-1 text-xs font-medium text-muted-foreground">{meta?.symbol ?? r.currency}</span>
                {Number(r.current).toLocaleString()}
              </span>
              <span className={cn("inline-flex items-center gap-0.5 text-xs font-semibold", tone)}>
                <Icon className="h-3 w-3" aria-hidden="true" />
                {deltaLabel}
              </span>
            </div>
          );
        })
      )}
    </button>
  );
}
