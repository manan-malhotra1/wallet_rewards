/**
 * Pure selectors that turn the analytics payload into plot-ready number
 * series.
 *
 * The dashboard's charts draw raw SVG, so they need `number[]`s and totals, not
 * the API's string decimals. Keeping that conversion here (DOM-free, under the
 * `admin-ui/lib/` coverage gate) means the per-currency invariant — money is
 * never summed across currencies — is enforced in one tested place rather than
 * in each chart component.
 */
import type {
  CurrencySeries,
  MetricsTimeseries,
  RevenueServiceSlice,
  RewardsTimeseries,
  NetFlowPoint,
  StatusBucket,
  UsersTimeseries,
} from "./api-types";

/** Which trend metric a tile drives. */
export type TrendMetric = "count" | "volume" | "revenue";

/** One plotted line: its buckets already converted to numbers. */
export interface TrendSeries {
  /** Stable key — the currency code, or "count" for the agnostic series. */
  key: string;
  /** Legend label. */
  label: string;
  values: number[];
  /** Currency symbol for tooltip values; empty for counts. */
  symbol: string;
}

/** Everything the trend chart needs for one metric + currency selection. */
export interface TrendData {
  /** Bucket keys, oldest first. */
  labels: string[];
  series: TrendSeries[];
  /**
   * The previous-period overlay, or null when it would be ambiguous.
   *
   * Only shown for a single series: with two currencies on the chart, one
   * dotted line can't say which currency it belongs to, so it is dropped
   * rather than mislabelled.
   */
  previous: number[] | null;
}

const EMPTY: TrendData = { labels: [], series: [], previous: null };

/** Parse an API string decimal, treating anything unparseable as 0. */
function amount(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Build the trend chart's series for the selected metric.
 *
 * @param data - the transactions timeseries, or null when its fetch failed
 * @param metric - which tile is charted
 * @param selectedCurrencies - drives series order for money metrics
 * @param currencySymbols - code → symbol, for tooltip formatting
 */
export function buildTrendData(
  data: MetricsTimeseries | null,
  metric: TrendMetric,
  selectedCurrencies: string[],
  currencySymbols: Record<string, string> = {},
): TrendData {
  if (!data) return EMPTY;

  if (metric === "count") {
    const current = data.count.current ?? [];
    if (current.length === 0) return EMPTY;
    return {
      labels: current.map((point) => point.bucket),
      series: [
        {
          key: "count",
          label: "Transactions",
          values: current.map((point) => point.count),
          symbol: "",
        },
      ],
      previous: (data.count.previous ?? []).map((point) => point.count),
    };
  }

  const pool: CurrencySeries[] = data[metric] ?? [];
  // Order by the selection, not the payload, so toggling a currency doesn't
  // reshuffle colours across the whole chart.
  const picked = selectedCurrencies
    .map((code) => pool.find((series) => series.currency === code))
    .filter((series): series is CurrencySeries => Boolean(series));
  if (picked.length === 0) return EMPTY;

  return {
    labels: picked[0].current.map((point) => point.bucket),
    series: picked.map((series) => ({
      key: series.currency,
      label: series.currency,
      values: series.current.map((point) => amount(point.value)),
      symbol: currencySymbols[series.currency] ?? "",
    })),
    previous:
      picked.length === 1 ? picked[0].previous.map((point) => amount(point.value)) : null,
  };
}

/**
 * The series behind a KPI tile's sparkline.
 *
 * Reuses the trend payload the dashboard already has, so a tile trend costs no
 * extra request. Money metrics spark on the first selected currency — the tile
 * lists every currency's figure, but one strip can only show one shape, and
 * summing them would break the never-sum rule.
 */
export function sparkValues(
  data: MetricsTimeseries | null,
  metric: TrendMetric,
  selectedCurrencies: string[],
): number[] {
  const { series } = buildTrendData(data, metric, selectedCurrencies);
  return series[0]?.values ?? [];
}

/** New-registration counts, oldest bucket first. */
export function registrationValues(data: UsersTimeseries | null): number[] {
  return (data?.current ?? []).map((point) => point.count);
}

/** Bucket keys for the registrations chart. */
export function registrationLabels(data: UsersTimeseries | null): string[] {
  return (data?.current ?? []).map((point) => point.bucket);
}

/** Transaction counts by terminal status, rolled up across every bucket. */
export interface StatusTotals {
  completed: number;
  pending: number;
  failed: number;
  total: number;
}

/**
 * Sum the per-bucket status breakdown into range totals.
 *
 * The panel answers "what share of this range succeeded", which is a single
 * proportion — so the buckets collapse rather than being drawn as a time series.
 */
export function statusTotals(buckets: StatusBucket[] | null): StatusTotals {
  const totals = (buckets ?? []).reduce(
    (acc, bucket) => ({
      completed: acc.completed + bucket.completed,
      pending: acc.pending + bucket.pending,
      failed: acc.failed + bucket.failed,
    }),
    { completed: 0, pending: 0, failed: 0 },
  );
  return { ...totals, total: totals.completed + totals.pending + totals.failed };
}

/** One service's revenue contribution within a single currency. */
export interface RevenueRow {
  serviceType: string;
  total: number;
}

/** Revenue rolled up per currency — never across currencies. */
export interface RevenueCurrencyGroup {
  currency: string;
  total: number;
  rows: RevenueRow[];
}

/**
 * Group revenue slices by currency, largest service first.
 *
 * Each currency gets its own subtotal because adding a USD fee to a ZAR fee
 * would be a meaningless number, however tempting a single "total revenue"
 * headline is.
 */
export function revenueByCurrency(
  slices: RevenueServiceSlice[] | null,
  selectedCurrencies: string[],
): RevenueCurrencyGroup[] {
  const groups: RevenueCurrencyGroup[] = [];
  for (const currency of selectedCurrencies) {
    const rows = (slices ?? [])
      .filter((slice) => slice.currency === currency)
      .map((slice) => ({ serviceType: slice.service_type, total: amount(slice.total) }))
      .sort((a, b) => b.total - a.total);
    if (rows.length === 0) continue;
    groups.push({
      currency,
      total: rows.reduce((sum, row) => sum + row.total, 0),
      rows,
    });
  }
  return groups;
}

/** One bucket of wallet movement for a single currency. */
export interface FlowPoint {
  bucket: string;
  inflow: number;
  outflow: number;
}

/** Wallet inflow/outflow for one currency, oldest bucket first. */
export function netFlowFor(points: NetFlowPoint[] | null, currency: string): FlowPoint[] {
  return (points ?? [])
    .filter((point) => point.currency === currency)
    .map((point) => ({
      bucket: point.bucket,
      inflow: amount(point.inflow),
      outflow: amount(point.outflow),
    }));
}

/** One bucket of rewards-points movement (unitless — points, not money). */
export interface PointsFlow {
  bucket: string;
  issued: number;
  redeemed: number;
}

/** Points issued vs redeemed per bucket, oldest first. */
export function rewardsFlow(data: RewardsTimeseries | null): PointsFlow[] {
  return (data?.points ?? []).map((point) => ({
    bucket: point.bucket,
    issued: amount(point.issued),
    redeemed: amount(point.redeemed),
  }));
}
