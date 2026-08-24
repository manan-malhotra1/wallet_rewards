/**
 * Server actions for the dashboard. The client component calls these when the
 * range/granularity changes so subsequent fetches run server-side with the
 * Keycloak bearer token — the browser never hits the backend directly.
 */
"use server";

import {
  getActiveUsers,
  getAnalyticsSummary,
  getCurrencies,
  getLiquidity,
  getNetFlow,
  getRevenueByService,
  getRewardsTimeseries,
  getTransactionsByService,
  getTransactionsByStatus,
  getTransactionsTimeseries,
  getUserTypeCatalog,
  getUsersByType,
  getUsersTimeseries,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

/**
 * Fetch every dashboard dataset for a range/granularity in one server round.
 * Uses allSettled so one failing panel doesn't blank the whole dashboard.
 */
export async function loadDashboardData(
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) {
  const tenantId = (await getActiveTenantId()) ?? "";

  const [
    summary,
    txnTimeseries,
    byService,
    byStatus,
    usersTs,
    activeUsers,
    revenue,
    rewards,
    liquidity,
    netFlow,
    usersByType,
    userTypeCatalog,
    currencies,
  ] = await Promise.allSettled([
    getAnalyticsSummary(tenantId, range),
    getTransactionsTimeseries(tenantId, range, granularity),
    getTransactionsByService(tenantId, range),
    getTransactionsByStatus(tenantId, range, granularity),
    getUsersTimeseries(tenantId, range, granularity),
    getActiveUsers(tenantId),
    getRevenueByService(tenantId, range),
    getRewardsTimeseries(tenantId, range, granularity),
    getLiquidity(tenantId),
    getNetFlow(tenantId, range, granularity),
    getUsersByType(tenantId),
    // The by-type chart labels its rows from the catalog: types are runtime
    // data, so a tenant's own type must read by name, not by raw code.
    getUserTypeCatalog(tenantId),
    getCurrencies(tenantId),
  ]);

  const val = <T>(r: PromiseSettledResult<T>): T | null =>
    r.status === "fulfilled" ? r.value : null;

  return {
    summary: val(summary),
    txnTimeseries: val(txnTimeseries),
    byService: val(byService),
    byStatus: val(byStatus),
    usersTs: val(usersTs),
    activeUsers: val(activeUsers),
    revenue: val(revenue),
    rewards: val(rewards),
    liquidity: val(liquidity),
    netFlow: val(netFlow),
    usersByType: val(usersByType),
    userTypeCatalog: val(userTypeCatalog),
    // Default to [] (not null) so the currency toggle always gets an array.
    currencies: val(currencies) ?? [],
  };
}

export type DashboardData = Awaited<ReturnType<typeof loadDashboardData>>;
