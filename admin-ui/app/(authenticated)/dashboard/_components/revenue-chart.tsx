"use client";

/**
 * Operator fee by service, one self-contained block per currency.
 *
 * Each currency gets its own subtotal and its own bar scale. Putting them side
 * by side rather than in a shared-axis grouped chart is what stops the eye from
 * comparing a USD bar against a ZAR bar — a comparison the numbers don't
 * support, and the reason revenue is never summed across currencies.
 */
import { formatCount } from "@/lib/analytics-format";
import { seriesColor } from "@/lib/chart-colors";
import { revenueByCurrency } from "@/lib/dashboard-series";
import { serviceLabel } from "@/lib/service-label";
import type { CurrencyInfo, RevenueServiceSlice } from "@/lib/api-types";
import { CodeChip, ShareBar } from "./indicators";

interface Props {
  data: RevenueServiceSlice[];
  selectedCurrencies: string[];
  currencyMeta: Record<string, CurrencyInfo>;
}

export function RevenueChart({ data, selectedCurrencies, currencyMeta }: Props) {
  const groups = revenueByCurrency(data, selectedCurrencies);
  if (groups.length === 0) return null;

  return (
    <div className="mt-3.5 grid gap-3.5 lg:grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">
      {groups.map((group) => {
        const symbol = currencyMeta[group.currency]?.symbol ?? "";
        const max = Math.max(...group.rows.map((row) => row.total));
        return (
          <div
            key={group.currency}
            className="rounded-[14px] bg-surface-inset p-4 shadow-[inset_0_1px_0_var(--hairline-top)]"
          >
            <div className="mb-3.5 flex items-center gap-2">
              <CodeChip code={group.currency} />
              <span className="text-xs text-muted-foreground">total</span>
              <span className="text-sm font-semibold text-foreground tabular-nums">
                {symbol} {formatCount(group.total)}
              </span>
            </div>
            <div className="flex flex-col gap-2.5">
              {group.rows.map((row, i) => (
                <div key={row.serviceType} className="flex flex-col gap-1.5">
                  <div className="flex items-baseline gap-2.5">
                    <span className="mr-auto text-[11.5px] text-foreground">
                      {serviceLabel(row.serviceType)}
                    </span>
                    <span className="text-xs font-semibold text-foreground tabular-nums">
                      {symbol} {formatCount(row.total)}
                    </span>
                  </div>
                  <ShareBar value={row.total} max={max} color={seriesColor(i)} />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
