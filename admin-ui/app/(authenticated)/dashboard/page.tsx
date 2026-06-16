/**
 * Dashboard — single-glance health of the active tenant.
 *
 * Layout matches FinOps Studio's ReconSense pattern:
 *   1. Top status bar (live indicator + exception count pill)
 *   2. Health metrics strip (4 inline KPIs separated by dividers)
 *   3. KPI cards (large tiles)
 *   4. Recent activity + alerts (side-by-side dense lists)
 */
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  FileCheck2,
  ScanLine,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { KpiCard } from "@/components/ui/kpi-card";
import { MetricsStrip } from "@/components/ui/metrics-strip";
import { StatusPill } from "@/components/ui/status-pill";
import { ApiError } from "@/lib/api";
import {
  listManualReview,
  listPendingRedemptions,
  listTenants,
  queryAuditLog,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import { formatTimestamp } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    const tenants = await listTenants().catch(() => []);
    if (tenants.length === 0) {
      return (
        <div className="p-6">
          <EmptyState
            icon={Sparkles}
            title="No tenants yet"
            description="Create the first tenant via the seed script or the Tenants page."
          />
        </div>
      );
    }
  }
  const tenantId = activeTenantId ?? "";

  const [pendingResult, manualResult, auditResult] = await Promise.allSettled([
    listPendingRedemptions(tenantId, 5),
    listManualReview(tenantId),
    queryAuditLog({ tenant_id: tenantId, limit: 10 }),
  ]);

  const pending = pendingResult.status === "fulfilled" ? pendingResult.value : [];
  const manualReview = manualResult.status === "fulfilled" ? manualResult.value : [];
  const auditEntries = auditResult.status === "fulfilled" ? auditResult.value : [];
  const totalExceptions = pending.length + manualReview.length;

  const fetchError =
    pendingResult.status === "rejected" && pendingResult.reason instanceof ApiError
      ? pendingResult.reason
      : null;

  return (
    <div className="flex h-full flex-col">
      {/* Top status bar */}
      <div className="flex items-center gap-3 border-b bg-background px-6 py-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Overview
          </h1>
          <p className="text-xs text-muted-foreground">
            Pending operations + recent activity across this tenant.
          </p>
        </div>
        <div className="flex-1" />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
          Live
        </span>
        <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 dark:border-red-500/20 dark:bg-red-500/10">
          <span className="text-lg font-bold text-red-600 dark:text-red-400">
            {totalExceptions}
          </span>
          <div className="flex flex-col leading-tight">
            <span className="text-[9px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
              Open
            </span>
            <span className="text-[9px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400">
              Exceptions
            </span>
          </div>
        </div>
      </div>

      {/* Health metrics strip */}
      <MetricsStrip
        items={[
          {
            label: "Pending recon",
            value: pending.length,
            icon: ScanLine,
            iconTone: "sky",
            valueTone: pending.length > 0 ? "amber" : "emerald",
          },
          {
            label: "Manual review",
            value: manualReview.length,
            icon: AlertTriangle,
            iconTone: "red",
            valueTone: manualReview.length > 0 ? "red" : "emerald",
          },
          {
            label: "Audit events",
            value: auditEntries.length,
            icon: Activity,
            iconTone: "violet",
          },
          {
            label: "System health",
            value: totalExceptions === 0 ? "OK" : "Attention",
            icon: FileCheck2,
            iconTone: totalExceptions === 0 ? "emerald" : "amber",
            valueTone: totalExceptions === 0 ? "emerald" : "amber",
          },
        ]}
      />

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6">
        {fetchError && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load some dashboard data"
            description={`${fetchError.errorCode}: ${fetchError.message}`}
          />
        )}

        {/* KPI grid */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Pending recon"
            value={pending.length}
            icon={ScanLine}
            iconTone={pending.length > 0 ? "amber" : "emerald"}
            subtext={
              pending.length > 0
                ? `oldest ${Math.max(...pending.map((p) => p.age_minutes))}m ago`
                : "all clear"
            }
          />
          <KpiCard
            label="Manual review"
            value={manualReview.length}
            icon={AlertTriangle}
            iconTone={manualReview.length > 0 ? "red" : "emerald"}
            subtext={
              manualReview.length > 0
                ? "operator action required"
                : "queue empty"
            }
          />
          <KpiCard
            label="Audit events"
            value={auditEntries.length}
            icon={TrendingUp}
            iconTone="violet"
            subtext="last 10 recorded"
          />
          <KpiCard
            label="Active users"
            value="—"
            icon={Users}
            iconTone="sky"
            subtext="Phase G metric"
          />
        </div>

        {/* Activity + Alerts side-by-side */}
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="rounded-lg border bg-card lg:col-span-2">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  Recent activity
                </h2>
                <p className="text-xs text-muted-foreground">
                  Last {auditEntries.length} entries from the audit log
                </p>
              </div>
              <Link
                href="/audit"
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                View all
                <ArrowUpRight className="h-3 w-3" />
              </Link>
            </div>
            {auditEntries.length === 0 ? (
              <EmptyState
                icon={Activity}
                title="No audit events yet"
                description="State-changing actions like rule creation, redemption confirmations, and admin overrides will appear here."
                className="py-10"
              />
            ) : (
              <ul className="divide-y">
                {auditEntries.map((entry) => (
                  <li
                    key={entry.id}
                    className="flex items-center gap-3 px-4 py-2.5"
                  >
                    <StatusPill
                      status={
                        entry.action.includes("rejected") ||
                        entry.action.includes("failed")
                          ? "FAILED"
                          : entry.action.includes("review")
                            ? "MANUAL_REVIEW"
                            : "ACTIVE"
                      }
                      variant="dense"
                    />
                    <span className="flex-1 truncate font-mono text-xs text-foreground">
                      {entry.action}
                    </span>
                    <Badge tone="neutral" className="font-mono text-[10px]">
                      {entry.actor_type}
                    </Badge>
                    <span className="w-[110px] text-right text-[11px] text-muted-foreground tabular">
                      {formatTimestamp(entry.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-lg border bg-card">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Alerts</h2>
                <p className="text-xs text-muted-foreground">
                  Items needing someone to look
                </p>
              </div>
            </div>
            <div className="space-y-2 p-3">
              {manualReview.slice(0, 4).map((item) => (
                <Link
                  key={item.redemption_id}
                  href="/redemption"
                  className="group flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm transition-colors hover:bg-red-100 dark:border-red-500/30 dark:bg-red-500/10 dark:hover:bg-red-500/15"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-400" />
                  <div className="flex-1">
                    <div className="text-xs font-semibold text-red-700 dark:text-red-300">
                      Redemption manual review
                    </div>
                    <div className="text-[11px] text-red-600/80 dark:text-red-400/80">
                      {item.amount} pts · retry {item.retry_count}
                    </div>
                  </div>
                  <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-red-600 opacity-0 transition-opacity group-hover:opacity-100 dark:text-red-400" />
                </Link>
              ))}
              {manualReview.length === 0 && pending.length === 0 && (
                <div className="flex flex-col items-center gap-2 rounded-md bg-emerald-500/5 px-3 py-6 text-center">
                  <CheckCircle2 className="h-6 w-6 text-emerald-500" />
                  <div>
                    <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                      All clear
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      No alerts to surface.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
