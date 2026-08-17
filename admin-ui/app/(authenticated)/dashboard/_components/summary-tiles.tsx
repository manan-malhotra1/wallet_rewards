/**
 * The two small-figure tiles: rolling active-user counts, and the per-currency
 * liquidity position.
 *
 * Both are read-only summaries with no chart of their own, so they share a
 * smaller-radius panel and a tighter type scale than the Overview KPIs — the
 * hierarchy is what tells the operator which row is the headline.
 *
 * Server-safe (no hooks, no `"use client"`).
 */
import { formatCount } from "@/lib/analytics-format";
import type { CurrencyLiquidity } from "@/lib/api-types";
import { CodeChip } from "./indicators";
import { TilePanel } from "./panel";

/** A labelled figure with an optional unit, e.g. DAU / WAU / MAU / Stickiness. */
export function MiniStat({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <TilePanel className="flex flex-col gap-1.5 px-4 py-3.5">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      <div className="flex items-baseline gap-1">
        <span className="text-xl leading-none font-semibold tracking-[-0.02em] text-foreground tabular-nums">
          {value}
        </span>
        {unit ? <span className="text-[11px] text-muted-foreground">{unit}</span> : null}
      </div>
    </TilePanel>
  );
}

/**
 * One currency's liquidity position: what the tenant owes wallet holders
 * against the cash float backing it.
 *
 * The two figures are stacked and hairline-separated rather than shown as a
 * ratio: a derived "coverage %" would imply a reconciliation this panel hasn't
 * done, and the operator's actual question is the two absolute numbers.
 */
export function LiquidityTile({
  entry,
  symbol,
}: {
  entry: CurrencyLiquidity;
  symbol: string;
}) {
  const rows = [
    { label: "Wallet liability", value: entry.wallet_liability },
    { label: "Cash float", value: entry.cash_float_balance },
  ];
  return (
    <TilePanel className="px-4 py-3.5">
      <CodeChip code={entry.currency} />
      <div className="mt-2.5">
        {rows.map((row, i) => (
          <div
            key={row.label}
            className={`flex items-baseline justify-between gap-3 ${
              i === 0 ? "border-b pt-0 pb-2.5" : "pt-2.5"
            }`}
          >
            <span className="text-[11.5px] text-muted-foreground">{row.label}</span>
            <span className="text-[15px] font-semibold tracking-[-0.015em] text-foreground tabular-nums">
              {symbol} {formatCount(Number(row.value))}
            </span>
          </div>
        ))}
      </div>
    </TilePanel>
  );
}
