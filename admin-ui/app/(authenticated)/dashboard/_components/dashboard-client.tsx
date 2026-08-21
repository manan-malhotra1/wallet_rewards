"use client";

/**
 * Dashboard client shell.
 *
 * Owns the selected range/granularity, the selected currencies (client-only —
 * the payload already carries every currency), and which stat tile drives the
 * shared trend chart. On range change it refetches every dataset via the server
 * action and syncs the URL params so a view is shareable.
 *
 * Content is grouped into labelled sections — Overview, Transactions, Users,
 * Revenue, Liquidity & Rewards — and each panel resolves its own ready/empty/
 * error state, so one failed fetch never blanks the page.
 */
import { useMemo, useState, useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { loadDashboardData, type DashboardData } from "../_actions";
import { formatCount, rangeLabel } from "@/lib/analytics-format";
import { CHART_SERIES } from "@/lib/chart-colors";
import {
  revenueByCurrency,
  sparkValues,
  statusTotals,
  type TrendMetric,
} from "@/lib/dashboard-series";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";
import { cn } from "@/lib/utils";

import { DashboardHeader } from "./dashboard-header";
import { MoneyStatTile } from "./money-stat-tile";
import { NetFlowChart } from "./net-flow-chart";
import { Panel, PanelHeading, SectionHeading } from "./panel";
import { BarsGlyph, PanelState, panelStatus } from "./panel-state";
import { RevenueChart } from "./revenue-chart";
import { RewardsChart } from "./rewards-chart";
import { ServiceMixChart } from "./service-mix-chart";
import { StatTile } from "./stat-tile";
import { StatusBreakdownChart } from "./status-breakdown-chart";
import { LiquidityTile, MiniStat } from "./summary-tiles";
import { TrendChart, TrendLegend } from "./trend-chart";
import { UsersGrowthChart } from "./users-growth-chart";
import { UserTypeChart } from "./user-type-chart";

interface Props {
  initial: DashboardData;
  initialRange: AnalyticsRange;
  initialGranularity: AnalyticsGranularity;
}

/** The trend metrics a tile can drive, and their headings. */
const TREND_LABEL: Record<TrendMetric, string> = {
  count: "Transactions",
  volume: "Volume",
  revenue: "Revenue",
};

export function DashboardClient({ initial, initialRange, initialGranularity }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [data, setData] = useState<DashboardData>(initial);
  const [range, setRange] = useState<AnalyticsRange>(initialRange);
  const [granularity, setGranularity] = useState<AnalyticsGranularity>(initialGranularity);
  const [metric, setMetric] = useState<TrendMetric>("count");
  const [selectedCurrencies, setSelectedCurrencies] = useState<string[]>(
    initial.currencies.map((c) => c.code),
  );
  const [pending, startTransition] = useTransition();

  const currencies = data.currencies;
  const currencyMeta = useMemo(
    () => Object.fromEntries(currencies.map((c) => [c.code, c])),
    [currencies],
  );

  function refetch(nextRange: AnalyticsRange, nextGranularity: AnalyticsGranularity) {
    setRange(nextRange);
    setGranularity(nextGranularity);
    const next = new URLSearchParams(params.toString());
    next.set("range", nextRange);
    next.set("granularity", nextGranularity);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    startTransition(async () => {
      const fresh = await loadDashboardData(nextRange, nextGranularity);
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

  const retry = () => refetch(range, granularity);

  const summary = data.summary;
  const activeUsers = data.activeUsers;
  const stickiness = activeUsers ? Number(activeUsers.stickiness) : null;
  const trendData = data.txnTimeseries;

  const caption = `${rangeLabel(range)} · by ${granularity} · ${selectedCurrencies.join(" / ")}`;
  const trendStatus = panelStatus(trendData, (trendData?.count.current.length ?? 0) === 0);

  const liquidity = selectedCurrencies
    .map((code) => (data.liquidity ?? []).find((l) => l.currency === code))
    .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry));

  return (
    <div>
      <DashboardHeader
        caption={caption}
        currencies={currencies}
        selectedCurrencies={selectedCurrencies}
        onCurrenciesChange={setSelectedCurrencies}
        range={range}
        granularity={granularity}
        onRangeChange={(r) => refetch(r, granularity)}
        onGranularityChange={(g) => refetch(range, g)}
      />

      <div
        aria-busy={pending}
        className={cn(
          "transition-[opacity,filter] duration-200 ease-out",
          pending && "pointer-events-none opacity-45 blur-[1.5px]",
        )}
      >
        {/* ---- Overview ---- */}
        <section className="mb-10">
          <SectionHeading title="Overview" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              id="count"
              label="Transactions"
              value={formatCount(Number(summary?.transaction_count.current ?? 0))}
              current={summary?.transaction_count.current ?? "0"}
              previous={summary?.transaction_count.previous ?? "0"}
              unit="txns"
              spark={sparkValues(trendData, "count", selectedCurrencies)}
              sparkColor={CHART_SERIES[0]}
              selected={metric === "count"}
              onSelect={() => setMetric("count")}
            />
            <MoneyStatTile
              id="volume"
              label="Volume"
              data={summary?.transaction_volume ?? []}
              selectedCurrencies={selectedCurrencies}
              currencyMeta={currencyMeta}
              spark={sparkValues(trendData, "volume", selectedCurrencies)}
              sparkColor={CHART_SERIES[1]}
              selected={metric === "volume"}
              onSelect={() => setMetric("volume")}
            />
            <MoneyStatTile
              id="revenue"
              label="Revenue"
              data={summary?.revenue_total ?? []}
              selectedCurrencies={selectedCurrencies}
              currencyMeta={currencyMeta}
              spark={sparkValues(trendData, "revenue", selectedCurrencies)}
              sparkColor={CHART_SERIES[2]}
              selected={metric === "revenue"}
              onSelect={() => setMetric("revenue")}
            />
            {/* Informational only — selecting it would leave the chart unchanged,
                so it is not selectable rather than a button that does nothing. */}
            <StatTile
              id="users_display"
              label="New users"
              value={formatCount(Number(summary?.new_users.current ?? 0))}
              current={summary?.new_users.current ?? "0"}
              previous={summary?.new_users.previous ?? "0"}
              unit="users"
              spark={data.usersTs?.current.map((p) => p.count) ?? []}
              sparkColor={CHART_SERIES[3]}
              selected={false}
              selectable={false}
              onSelect={() => {}}
            />
          </div>

          <Panel className="mt-3.5">
            <PanelHeading
              title={`${TREND_LABEL[metric]} over time`}
              subtitle={
                metric === "count"
                  ? "Dotted line is the previous period"
                  : selectedCurrencies.length === 1
                    ? `One series for ${selectedCurrencies[0]} · dotted line is the previous period`
                    : "One series per selected currency · never summed across currencies"
              }
              action={
                trendStatus === "ready" && trendData ? (
                  <TrendLegend
                    data={trendData}
                    metric={metric}
                    selectedCurrencies={selectedCurrencies}
                  />
                ) : null
              }
            />
            <div className="mt-4">
              <PanelState
                status={trendStatus}
                emptyMessage="No activity in this range."
                emptyClassName="h-[300px]"
                onRetry={retry}
              >
                {trendData ? (
                  <TrendChart
                    data={trendData}
                    metric={metric}
                    selectedCurrencies={selectedCurrencies}
                    currencyMeta={currencyMeta}
                    granularity={granularity}
                    range={range}
                  />
                ) : null}
              </PanelState>
            </div>
          </Panel>
        </section>

        {/* ---- Transactions ---- */}
        <section className="mb-10">
          <SectionHeading title="Transactions" />
          <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:items-start">
            <Panel>
              <PanelHeading title="Service mix" subtitle="Counts by service type" />
              <PanelState
                // Emptiness is "nothing to draw", not "no rows": a payload of
                // all-zero services would otherwise be classed ready and render
                // an empty card.
                status={panelStatus(
                  data.byService,
                  (data.byService ?? []).every((s) => s.count === 0),
                )}
                emptyMessage="No transactions yet."
                onRetry={retry}
              >
                {data.byService ? <ServiceMixChart data={data.byService} /> : null}
              </PanelState>
            </Panel>

            <Panel>
              <PanelHeading
                title="Transaction status"
                subtitle="Completed / pending / failed breakdown"
              />
              <PanelState
                status={panelStatus(data.byStatus, statusTotals(data.byStatus).total === 0)}
                emptyMessage="No transactions yet."
                emptyClassName="mt-3.5 h-[150px]"
                onRetry={retry}
              >
                {data.byStatus ? <StatusBreakdownChart data={data.byStatus} /> : null}
              </PanelState>
            </Panel>
          </div>
        </section>

        {/* ---- Users ---- */}
        <section className="mb-10">
          <SectionHeading title="Users" hint="Active users over rolling windows" />
          <div className="mb-2.5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            <MiniStat label="DAU" value={formatCount(activeUsers?.dau ?? 0)} unit="users" />
            <MiniStat label="WAU" value={formatCount(activeUsers?.wau ?? 0)} unit="users" />
            <MiniStat label="MAU" value={formatCount(activeUsers?.mau ?? 0)} unit="users" />
            <MiniStat
              label="Stickiness"
              value={stickiness === null ? "—" : (stickiness * 100).toFixed(1)}
              unit={stickiness === null ? undefined : "%"}
            />
          </div>
          <div className="grid gap-3.5 lg:grid-cols-2">
            <Panel>
              <PanelHeading
                title="New registrations"
                subtitle={`By ${granularity}, ${rangeLabel(range).toLowerCase()}`}
              />
              <PanelState
                status={panelStatus(data.usersTs, (data.usersTs?.current.length ?? 0) === 0)}
                emptyMessage="No activity in this range."
                onRetry={retry}
              >
                {data.usersTs ? (
                  <UsersGrowthChart
                    data={data.usersTs}
                    granularity={granularity}
                    range={range}
                  />
                ) : null}
              </PanelState>
            </Panel>

            <Panel>
              <PanelHeading title="Users by type" subtitle="Share of the registered base" />
              <PanelState
                status={panelStatus(
                  data.usersByType,
                  (data.usersByType ?? []).every((slice) => slice.count === 0),
                )}
                emptyMessage="No users yet."
                onRetry={retry}
              >
                {data.usersByType ? <UserTypeChart data={data.usersByType} /> : null}
              </PanelState>
            </Panel>
          </div>
        </section>

        {/* ---- Revenue ---- */}
        <section className="mb-10">
          <SectionHeading title="Revenue" />
          <Panel>
            <PanelHeading
              title="Revenue by service"
              subtitle="Operator fee, per currency (tax & commission excluded)"
            />
            <PanelState
              // Classed empty when no *selected* currency has revenue — a
              // payload that only covers deselected currencies has nothing to
              // render, so it must not be treated as ready.
              status={panelStatus(
                data.revenue,
                revenueByCurrency(data.revenue, selectedCurrencies).length === 0,
              )}
              emptyMessage="No revenue in this range."
              emptyIcon={BarsGlyph}
              emptyClassName="mt-3.5 h-[170px]"
              onRetry={retry}
            >
              {data.revenue ? (
                <RevenueChart
                  data={data.revenue}
                  selectedCurrencies={selectedCurrencies}
                  currencyMeta={currencyMeta}
                />
              ) : null}
            </PanelState>
          </Panel>
        </section>

        {/* ---- Liquidity & Rewards ---- */}
        <section className="mb-10">
          <SectionHeading title="Liquidity &amp; Rewards" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(auto-fit,minmax(230px,1fr))]">
            {liquidity.map((entry) => (
              <LiquidityTile
                key={entry.currency}
                entry={entry}
                symbol={currencyMeta[entry.currency]?.symbol ?? ""}
              />
            ))}
          </div>

          <div className="mt-2.5 grid gap-3.5 lg:grid-cols-2">
            {selectedCurrencies.map((code) => (
              <Panel key={code}>
                <PanelHeading
                  title={`Net flow · ${code}`}
                  subtitle="Customer wallets: inflow vs outflow"
                  action={
                    <div className="flex items-center gap-3.5">
                      <Legend color="var(--chart-1)" label="Inflow" />
                      <Legend color="var(--chart-4)" label="Outflow" />
                    </div>
                  }
                />
                <PanelState
                  status={panelStatus(
                    data.netFlow,
                    (data.netFlow ?? []).every((p) => p.currency !== code),
                  )}
                  emptyMessage="No wallet movement."
                  emptyIcon={BarsGlyph}
                  emptyClassName="mt-3.5 h-[200px]"
                  onRetry={retry}
                >
                  <NetFlowChart
                    data={data.netFlow ?? []}
                    currency={code}
                    symbol={currencyMeta[code]?.symbol ?? ""}
                    granularity={granularity}
                    range={range}
                  />
                </PanelState>
              </Panel>
            ))}

            {/* Operator treasury movement gets its own panel and therefore its own
                y-scale: float top-ups run orders of magnitude above customer
                activity, and folding them into the wallet series would both flatten
                those bars and misreport operator funding as customer inflow. */}
            {selectedCurrencies.map((code) => (
              <Panel key={`treasury-${code}`}>
                <PanelHeading
                  title={`Treasury flow · ${code}`}
                  subtitle="Operator cash: bank vs float"
                  action={
                    <div className="flex items-center gap-3.5">
                      <Legend color="var(--chart-1)" label="From bank" />
                      <Legend color="var(--chart-4)" label="To bank" />
                    </div>
                  }
                />
                <PanelState
                  status={panelStatus(
                    data.netFlow,
                    (data.netFlow ?? []).every(
                      (p) =>
                        p.currency !== code ||
                        (Number(p.treasury_inflow) === 0 && Number(p.treasury_outflow) === 0),
                    ),
                  )}
                  emptyMessage="No treasury movement."
                  emptyIcon={BarsGlyph}
                  emptyClassName="mt-3.5 h-[200px]"
                  onRetry={retry}
                >
                  <NetFlowChart
                    data={data.netFlow ?? []}
                    currency={code}
                    symbol={currencyMeta[code]?.symbol ?? ""}
                    granularity={granularity}
                    range={range}
                    series="treasury"
                  />
                </PanelState>
              </Panel>
            ))}

            <Panel>
              <PanelHeading
                title="Points issued vs redeemed"
                subtitle="Rewards ledger, unitless"
                action={
                  <div className="flex items-center gap-3.5">
                    <Legend color="var(--chart-1)" label="Issued" />
                    <Legend color="var(--chart-5)" label="Redeemed" />
                  </div>
                }
              />
              <PanelState
                status={panelStatus(data.rewards, (data.rewards?.points.length ?? 0) === 0)}
                emptyMessage="No rewards activity in this range."
                emptyIcon={BarsGlyph}
                emptyClassName="mt-3.5 h-[200px]"
                onRetry={retry}
              >
                {data.rewards ? (
                  <RewardsChart data={data.rewards} granularity={granularity} range={range} />
                ) : null}
              </PanelState>
            </Panel>
          </div>
        </section>
      </div>
    </div>
  );
}

/** A compact swatch + label pair for a panel header. */
function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-[7px] text-[11.5px] text-muted-foreground">
      <span
        aria-hidden="true"
        className="inline-block size-2.5 rounded-[3px]"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}
