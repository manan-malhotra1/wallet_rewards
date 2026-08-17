"use client";

/**
 * A money KPI tile: one hairline-separated row per selected currency.
 *
 * Values are never summed across currencies — the rows are the KPI, not a
 * breakdown of one. Each row carries its own compact delta against that
 * currency's previous period, and the currency symbol sits adjacent to the
 * figure so a bare number can never be misread as the wrong money.
 */
import { CHART_SERIES } from "@/lib/chart-colors";
import { formatCount } from "@/lib/analytics-format";
import type { CurrencyInfo, CurrencyScalar } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { DeltaChip } from "./indicators";
import { TileShell } from "./metric-tile-shell";

interface Props {
  id: string;
  label: string;
  data: CurrencyScalar[];
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
  /** Series for the tile sparkline (the first selected currency). */
  spark?: number[];
  sparkColor?: string;
  selected: boolean;
  onSelect: (id: string) => void;
}

export function MoneyStatTile({
  id,
  label,
  data,
  selectedCurrencies,
  currencyMeta,
  spark = [],
  sparkColor = CHART_SERIES[1],
  selected,
  onSelect,
}: Props) {
  // Drive row order off the selection, not the payload, so toggling a currency
  // reorders predictably instead of following the API's ordering.
  const rows = selectedCurrencies
    .map((code) => data.find((d) => d.currency === code))
    .filter((d): d is CurrencyScalar => Boolean(d));

  return (
    <TileShell
      id={id}
      label={label}
      selected={selected}
      onSelect={onSelect}
      spark={spark}
      sparkColor={sparkColor}
    >
      {rows.length === 0 ? (
        <div className="mt-2.5 flex items-end gap-3">
          <span className="text-[30px] leading-none font-semibold tracking-[-0.02em] text-foreground tabular-nums">
            —
          </span>
        </div>
      ) : (
        <div className="mt-2">
          {rows.map((row, i) => (
            <div
              key={row.currency}
              className={cn(
                "flex items-center justify-between gap-2.5",
                i === 0 ? "pt-1.5 pb-2.5" : "border-t py-2.5",
              )}
            >
              <div className="flex min-w-0 items-baseline gap-1">
                <span className="text-xs font-medium text-muted-foreground">
                  {currencyMeta[row.currency]?.symbol ?? row.currency}
                </span>
                <span className="text-[21px] leading-tight font-semibold tracking-[-0.02em] text-foreground tabular-nums">
                  {formatCount(Number(row.current))}
                </span>
                <span className="text-[10px] tracking-[0.06em] text-muted-foreground">
                  {row.currency}
                </span>
              </div>
              <DeltaChip current={row.current} previous={row.previous} compact />
            </div>
          ))}
        </div>
      )}
    </TileShell>
  );
}
