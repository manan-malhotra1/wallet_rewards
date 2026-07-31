"use client";

/**
 * Dashboard client shell. Owns the selected range/granularity, the selected
 * currencies (client-only — the payload already carries every currency), and
 * the selected stat tile (which metric the shared trend chart plots). On range
 * change it refetches all datasets via the server action and syncs URL params
 * for a shareable view. The content is grouped into labeled sections:
 * Overview, Transactions, Users, Revenue, and Liquidity & Rewards.
 */
import { useMemo, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { loadDashboardData, type DashboardData } from "../_actions";
import { CurrencyToggle } from "./currency-toggle";
import { MoneyStatTile } from "./money-stat-tile";
import { StatTile } from "./stat-tile";
import { TimeRangeSwitcher } from "./time-range-switcher";
import { TrendChart } from "./trend-chart";
import { ServiceMixChart } from "./service-mix-chart";
import { StatusBreakdownChart } from "./status-breakdown-chart";
import { UsersGrowthChart } from "./users-growth-chart";
import { RevenueChart } from "./revenue-chart";
import { RewardsChart } from "./rewards-chart";
import { NetFlowChart } from "./net-flow-chart";
import { UserTypeChart } from "./user-type-chart";
import { Card } from "@/components/ui/card";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

interface Props {
  initial: DashboardData;
  initialRange: AnalyticsRange;
  initialGranularity: AnalyticsGranularity;
}

/** The trend metrics a money/count tile can drive. */
type TrendMetric = "count" | "volume" | "revenue";
const TREND_METRICS: TrendMetric[] = ["count", "volume", "revenue"];
const TREND_LABEL: Record<TrendMetric, string> = {
  count: "Transactions",
  volume: "Volume",
  revenue: "Revenue",
};

/** A labeled divider that opens each dashboard section. */
function SectionHeading({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-3 mt-8 flex items-baseline gap-2 border-b pb-1.5">
      <h2 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</h2>
      {hint ? <span className="text-[11px] text-muted-foreground/70">{hint}</span> : null}
    </div>
  );
}

/** A small label + value stat block (used for DAU/WAU/MAU and liquidity). */
function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-bold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

export function DashboardClient({ initial, initialRange, initialGranularity }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [data, setData] = useState<DashboardData>(initial);
  const [range, setRange] = useState<AnalyticsRange>(initialRange);
  const [granularity, setGranularity] = useState<AnalyticsGranularity>(initialGranularity);
  const [selected, setSelected] = useState<string>("count");
  const [selectedCurrencies, setSelectedCurrencies] = useState<string[]>(
    initial.currencies.map((c) => c.code),
  );
  const [pending, startTransition] = useTransition();

  const currencies = data.currencies;
  const currencyMeta = useMemo(
    () => Object.fromEntries(currencies.map((c) => [c.code, c])),
    [currencies],
  );

  function refetch(r: AnalyticsRange, g: AnalyticsGranularity) {
    setRange(r);
    setGranularity(g);
    const next = new URLSearchParams(params.toString());
    next.set("range", r);
    next.set("granularity", g);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    startTransition(async () => {
      const fresh = await loadDashboardData(r, g);
      setData(fresh);
      // Intersect the current selection with the new currency set; fall back to
      // all new codes if the intersection is empty (e.g. tenant switched).
      const codes = fresh.currencies.map((c) => c.code);
      setSelectedCurrencies((prev) => {
        const kept = prev.filter((c) => codes.includes(c));
        return kept.length > 0 ? kept : codes;
      });
    });
  }

  // The New-users tile is informational — clicking it never changes the trend.
  const trendMetric: TrendMetric = TREND_METRICS.includes(selected as TrendMetric)
    ? (selected as TrendMetric)
    : "count";
  const trendLabel = TREND_LABEL[trendMetric];

  const s = data.summary;
  const activeUsers = data.activeUsers;
  const stickiness = activeUsers ? Number(activeUsers.stickiness) : null;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight">Overview</h1>
        <div className="flex flex-wrap items-center gap-3">
          <CurrencyToggle
            currencies={currencies}
            selected={selectedCurrencies}
            onChange={setSelectedCurrencies}
          />
          <TimeRangeSwitcher
            range={range}
            granularity={granularity}
            onRangeChange={(r) => refetch(r, granularity)}
            onGranularityChange={(g) => refetch(range, g)}
          />
        </div>
      </div>

      <div
        aria-busy={pending}
        className={
          pending
            ? "pointer-events-none opacity-70 transition-opacity duration-200 ease-out"
            : "transition-opacity duration-200 ease-out"
        }
      >
        {/* ---- Overview tiles ---- */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          id="count"
          label="Transactions"
          value={Number(s?.transaction_count.current ?? 0).toLocaleString()}
          current={s?.transaction_count.current ?? "0"}
          previous={s?.transaction_count.previous ?? "0"}
          selected={selected === "count"}
          onSelect={setSelected}
        />
        <MoneyStatTile
          id="volume"
          label="Volume"
          data={s?.transaction_volume ?? []}
          selectedCurrencies={selectedCurrencies}
          currencyMeta={currencyMeta}
          selected={selected === "volume"}
          onSelect={setSelected}
        />
        <MoneyStatTile
          id="revenue"
          label="Revenue"
          data={s?.revenue_total ?? []}
          selectedCurrencies={selectedCurrencies}
          currencyMeta={currencyMeta}
          selected={selected === "revenue"}
          onSelect={setSelected}
        />
        <StatTile
          id="users_display"
          label="New users"
          value={Number(s?.new_users.current ?? 0).toLocaleString()}
          current={s?.new_users.current ?? "0"}
          previous={s?.new_users.previous ?? "0"}
          selected={false}
          onSelect={() => {}}
        />
      </div>

      {/* Shared trend chart driven by the selected tile. */}
      <Card className="mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold">{trendLabel} over time</h2>
        {data.txnTimeseries ? (
          <TrendChart
            data={data.txnTimeseries}
            metric={trendMetric}
            selectedCurrencies={selectedCurrencies}
            currencyMeta={currencyMeta}
          />
        ) : null}
      </Card>

      {/* ---- Transactions ---- */}
      <SectionHeading title="Transactions" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Service mix</h2>
          {data.byService ? <ServiceMixChart data={data.byService} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Transaction status</h2>
          {data.byStatus ? <StatusBreakdownChart data={data.byStatus} /> : null}
        </Card>
      </div>

      {/* ---- Users ---- */}
      <SectionHeading title="Users" hint="Active users over rolling windows" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniStat label="DAU" value={Number(activeUsers?.dau ?? 0).toLocaleString()} />
        <MiniStat label="WAU" value={Number(activeUsers?.wau ?? 0).toLocaleString()} />
        <MiniStat label="MAU" value={Number(activeUsers?.mau ?? 0).toLocaleString()} />
        <MiniStat
          label="Stickiness"
          value={stickiness === null ? "—" : `${(stickiness * 100).toFixed(0)}%`}
        />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">New registrations</h2>
          {data.usersTs ? <UsersGrowthChart data={data.usersTs} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Users by type</h2>
          {data.usersByType ? <UserTypeChart data={data.usersByType} /> : null}
        </Card>
      </div>

      {/* ---- Revenue ---- */}
      <SectionHeading title="Revenue" />
      <Card className="p-4">
        <h2 className="text-sm font-semibold">Revenue by service</h2>
        <p className="mb-2 text-xs text-muted-foreground">
          Operator fee, per currency (tax &amp; commission excluded)
        </p>
        {data.revenue ? (
          <RevenueChart
            data={data.revenue}
            selectedCurrencies={selectedCurrencies}
            currencyMeta={currencyMeta}
          />
        ) : null}
      </Card>

      {/* ---- Liquidity & Rewards ---- */}
      <SectionHeading title="Liquidity & Rewards" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {selectedCurrencies
          .map((code) => (data.liquidity ?? []).find((l) => l.currency === code))
          .filter((l): l is NonNullable<typeof l> => Boolean(l))
          .map((l) => (
            <div key={l.currency} className="rounded-lg border bg-card p-4">
              <div className="text-xs font-semibold text-muted-foreground">{l.currency}</div>
              <div className="mt-1 flex items-baseline justify-between gap-2">
                <span className="text-[11px] text-muted-foreground">Wallet liability</span>
                <span className="text-sm font-bold tabular-nums">
                  {Number(l.wallet_liability).toLocaleString()}
                </span>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] text-muted-foreground">Cash float</span>
                <span className="text-sm font-bold tabular-nums">
                  {Number(l.cash_float_balance).toLocaleString()}
                </span>
              </div>
            </div>
          ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {selectedCurrencies.map((code) => (
          <Card key={code} className="p-4">
            <h2 className="mb-2 text-sm font-semibold">Net flow · {code}</h2>
            <NetFlowChart data={data.netFlow ?? []} currency={code} />
          </Card>
        ))}
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Points issued vs redeemed</h2>
          {data.rewards ? <RewardsChart data={data.rewards} /> : null}
        </Card>
      </div>
      </div>
    </div>
  );
}
