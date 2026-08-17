"use client";

/**
 * The dashboard's sticky filter bar.
 *
 * Pinned to the top of the page's scroll container and blurred, because this is
 * a long page and the range/currency controls are the ones an operator reaches
 * for after scrolling — a header that scrolls away means scrolling back up to
 * change the window.
 *
 * Deliberately does NOT repeat the tenant name or the theme toggle: both
 * already live in the app shell's topbar directly above this, and duplicating
 * them would give the same control two places to disagree.
 */
import { CurrencyToggle } from "./currency-toggle";
import { TimeRangeSwitcher } from "./time-range-switcher";
import type { AnalyticsGranularity, AnalyticsRange, CurrencyInfo } from "@/lib/api-types";

interface Props {
  /** Human summary of the active window, e.g. "Last 30 days · by day · USD / ZAR". */
  caption: string;
  currencies: CurrencyInfo[];
  selectedCurrencies: string[];
  onCurrenciesChange: (codes: string[]) => void;
  range: AnalyticsRange;
  granularity: AnalyticsGranularity;
  onRangeChange: (range: AnalyticsRange) => void;
  onGranularityChange: (granularity: AnalyticsGranularity) => void;
}

export function DashboardHeader({
  caption,
  currencies,
  selectedCurrencies,
  onCurrenciesChange,
  range,
  granularity,
  onRangeChange,
  onGranularityChange,
}: Props) {
  return (
    <header className="sticky top-0 z-30 -mx-6 mb-6 flex flex-wrap items-center gap-x-5 gap-y-4 border-b bg-[var(--glass-header)] px-6 py-3.5 shadow-[inset_0_1px_0_var(--hairline-top)] backdrop-blur-[18px] backdrop-saturate-[140%]">
      <div className="mr-auto flex flex-col gap-0.5">
        <h1 className="text-[17px] font-semibold tracking-[-0.015em] text-foreground">Analytics</h1>
        <span className="text-[11px] text-muted-foreground tabular-nums">{caption}</span>
      </div>

      <CurrencyToggle
        currencies={currencies}
        selected={selectedCurrencies}
        onChange={onCurrenciesChange}
      />

      <TimeRangeSwitcher
        range={range}
        granularity={granularity}
        onRangeChange={onRangeChange}
        onGranularityChange={onGranularityChange}
      />
    </header>
  );
}
