"use client";

/**
 * Dashboard client shell. Owns the selected range/granularity and the
 * selected stat tile (which metric the shared trend chart plots). On range
 * change it refetches all datasets via the server action and syncs URL params
 * for a shareable view.
 */
import { useTransition, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { loadDashboardData, type DashboardData } from "../_actions";
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

const TILES = [
  { id: "count", label: "Transactions", metric: "count" as const, from: "transaction_count" as const },
  { id: "volume", label: "Volume", metric: "volume" as const, from: "transaction_volume" as const },
  { id: "revenue", label: "Revenue", metric: "volume" as const, from: "revenue_total" as const },
  { id: "users", label: "New users", metric: "count" as const, from: "new_users" as const },
];

export function DashboardClient({ initial, initialRange, initialGranularity }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [data, setData] = useState<DashboardData>(initial);
  const [range, setRange] = useState<AnalyticsRange>(initialRange);
  const [granularity, setGranularity] = useState<AnalyticsGranularity>(initialGranularity);
  const [selected, setSelected] = useState<string>("count");
  const [pending, startTransition] = useTransition();

  function refetch(r: AnalyticsRange, g: AnalyticsGranularity) {
    setRange(r);
    setGranularity(g);
    const next = new URLSearchParams(params.toString());
    next.set("range", r);
    next.set("granularity", g);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    startTransition(async () => setData(await loadDashboardData(r, g)));
  }

  const selectedTile = TILES.find((t) => t.id === selected) ?? TILES[0];
  const s = data.summary;

  return (
    <div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight">Overview</h1>
        <TimeRangeSwitcher
          range={range}
          granularity={granularity}
          onRangeChange={(r) => refetch(r, granularity)}
          onGranularityChange={(g) => refetch(range, g)}
        />
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {TILES.map((t) => {
          const scalar = s?.[t.from] ?? { current: "0", previous: "0" };
          return (
            <StatTile
              key={t.id}
              id={t.id}
              label={t.label}
              value={Number(scalar.current).toLocaleString()}
              current={scalar.current}
              previous={scalar.previous}
              selected={selected === t.id}
              onSelect={setSelected}
            />
          );
        })}
      </div>

      {/* Shared trend + service mix */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-4 lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold">{selectedTile.label} over time</h2>
          {data.txnTimeseries ? (
            <TrendChart data={data.txnTimeseries} metric={selectedTile.metric} label={selectedTile.label} />
          ) : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Service mix</h2>
          {data.byService ? <ServiceMixChart data={data.byService} /> : null}
        </Card>
      </div>

      {/* Status + users */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Transaction status</h2>
          {data.byStatus ? <StatusBreakdownChart data={data.byStatus} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">New registrations</h2>
          {data.usersTs ? <UsersGrowthChart data={data.usersTs} /> : null}
        </Card>
      </div>

      {/* Revenue + rewards */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Revenue by service</h2>
          {data.revenue ? <RevenueChart data={data.revenue} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Points issued vs redeemed</h2>
          {data.rewards ? <RewardsChart data={data.rewards} /> : null}
        </Card>
      </div>

      {/* Liquidity + user mix */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-2 gap-3 lg:col-span-1">
          <div className="rounded-lg border bg-card p-4">
            <div className="text-xs text-muted-foreground">Wallet liability</div>
            <div className="text-xl font-bold tabular-nums">
              {Number(data.liquidity?.wallet_liability ?? 0).toLocaleString()}
            </div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <div className="text-xs text-muted-foreground">Cash float</div>
            <div className="text-xl font-bold tabular-nums">
              {Number(data.liquidity?.cash_float_balance ?? 0).toLocaleString()}
            </div>
          </div>
        </div>
        <Card className="p-4 lg:col-span-1">
          <h2 className="mb-2 text-sm font-semibold">Net flow (in vs out)</h2>
          {data.netFlow ? <NetFlowChart data={data.netFlow} /> : null}
        </Card>
        <Card className="p-4 lg:col-span-1">
          <h2 className="mb-2 text-sm font-semibold">Users by type</h2>
          {data.usersByType ? <UserTypeChart data={data.usersByType} /> : null}
        </Card>
      </div>
    </div>
  );
}
