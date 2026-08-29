/**
 * Dashboard — interactive KPI overview for the active tenant.
 *
 * Server component: resolves the active tenant, reads range/granularity from
 * URL params, does the initial analytics fetch, and hands off to the client
 * shell which owns interactivity (tile selection, range switching, refetch).
 */
import { EmptyState } from "@/components/ui/empty-state";
import { Sparkles } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { listTenants } from "@/lib/api-endpoints";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";
import { loadDashboardData } from "./_actions";
import { DashboardClient } from "./_components/dashboard-client";

export const dynamic = "force-dynamic";

const RANGES: AnalyticsRange[] = ["24h", "7d", "30d", "quarter"];
const GRANS: AnalyticsGranularity[] = ["day", "week", "month"];

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; granularity?: string }>;
}) {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    const tenants = await listTenants().catch(() => []);
    if (tenants.length === 0) {
      return (
        <div className="p-6">
          <EmptyState
            icon={Sparkles}
            title="No tenants yet"
            description="Create the first tenant on the Tenants page."
          />
        </div>
      );
    }
  }

  const sp = await searchParams;
  const range: AnalyticsRange = RANGES.includes(sp.range as AnalyticsRange)
    ? (sp.range as AnalyticsRange)
    : "7d";
  const granularity: AnalyticsGranularity = GRANS.includes(sp.granularity as AnalyticsGranularity)
    ? (sp.granularity as AnalyticsGranularity)
    : "day";

  const initial = await loadDashboardData(range, granularity);

  return (
    // Horizontal padding only: the sticky filter bar inside DashboardClient
    // bleeds to the edges with a negative margin, so top padding here would
    // leave a transparent strip above it as the page scrolls under.
    <div className="h-full overflow-y-auto px-6 pb-14">
      {/*
        key on the tenant id forces a full remount when the active tenant
        changes. Without it, router.refresh() re-renders this server component
        with the new tenant's `initial` prop but DashboardClient's useState
        (data + selected currencies) keeps the PREVIOUS tenant's values, showing
        one tenant's currencies/figures under another. Remounting resets state.
      */}
      <DashboardClient
        key={activeTenantId ?? "none"}
        initial={initial}
        initialRange={range}
        initialGranularity={granularity}
      />
    </div>
  );
}
