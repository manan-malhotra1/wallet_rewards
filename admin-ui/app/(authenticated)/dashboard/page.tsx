/**
 * Dashboard — single-glance health of the active tenant.
 *
 * Pulls reconciliation pending + manual-review + recent audit entries to
 * build KPI cards and an alerts strip. Refreshes every navigation; no
 * client-side polling yet (Phase G adds Suspense + revalidate).
 */
import {
  AlertTriangle,
  Coins,
  ScanLine,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import Link from "next/link";

import { getActiveTenantId } from "@/lib/active-tenant";
import {
  listManualReview,
  listPendingRedemptions,
  listTenants,
  queryAuditLog,
} from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { StatusPill } from "@/components/ui/status-pill";
import { formatTimestamp } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface KpiCardProps {
  label: string;
  value: string;
  delta?: string;
  tone?: "neutral" | "warning" | "danger" | "success";
  icon: React.ComponentType<{ className?: string }>;
  href?: string;
}

function KpiCard({ label, value, delta, tone = "neutral", icon: Icon, href }: KpiCardProps) {
  const toneClass =
    tone === "warning"
      ? "border-[--color-warning]/40"
      : tone === "danger"
        ? "border-[--color-danger]/40"
        : tone === "success"
          ? "border-[--color-success]/40"
          : "";
  const content = (
    <div
      className={`rounded-lg border border-[--color-border] bg-[--color-surface-1] p-4 ${toneClass}`}
    >
      <div className="flex items-start justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[--color-text-3]">
          {label}
        </span>
        <Icon className="h-4 w-4 text-[--color-text-3]" />
      </div>
      <div className="mt-3 font-mono text-[24px] font-semibold tabular text-[--color-text-1]">
        {value}
      </div>
      {delta && (
        <div className="mt-1 text-[12px] text-[--color-text-2]">{delta}</div>
      )}
    </div>
  );
  if (href) {
    return (
      <Link href={href} className="block transition-opacity hover:opacity-90">
        {content}
      </Link>
    );
  }
  return content;
}

export default async function DashboardPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    // No tenants in the system yet — render an instructive empty state.
    const tenants = await listTenants().catch(() => []);
    if (tenants.length === 0) {
      return (
        <div className="px-6 py-8">
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

  // Fetch dashboard data in parallel; tolerate individual failures.
  const [pendingResult, manualResult, auditResult] = await Promise.allSettled([
    listPendingRedemptions(tenantId, 5),
    listManualReview(tenantId),
    queryAuditLog({ tenant_id: tenantId, limit: 10 }),
  ]);

  const pending =
    pendingResult.status === "fulfilled" ? pendingResult.value : [];
  const manualReview =
    manualResult.status === "fulfilled" ? manualResult.value : [];
  const auditEntries =
    auditResult.status === "fulfilled" ? auditResult.value : [];

  const fetchError =
    pendingResult.status === "rejected" && pendingResult.reason instanceof ApiError
      ? pendingResult.reason
      : null;

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Pending operations + recent activity across this tenant."
      />
      <div className="px-6 py-6">
        {fetchError && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load some dashboard data"
            description={`${fetchError.errorCode}: ${fetchError.message}`}
          />
        )}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard
            label="Pending recon"
            value={String(pending.length)}
            delta={
              pending.length > 0
                ? `oldest ${Math.max(...pending.map((p) => p.age_minutes))}m`
                : "all clear"
            }
            tone={pending.length > 0 ? "warning" : "success"}
            icon={ScanLine}
            href="/reconciliation"
          />
          <KpiCard
            label="Manual review"
            value={String(manualReview.length)}
            delta={
              manualReview.length > 0
                ? "operator action required"
                : "queue empty"
            }
            tone={manualReview.length > 0 ? "danger" : "success"}
            icon={AlertTriangle}
            href="/redemption"
          />
          <KpiCard
            label="Audit events"
            value={String(auditEntries.length)}
            delta="last 10 recorded"
            icon={TrendingUp}
            href="/audit"
          />
          <KpiCard
            label="Active users"
            value="—"
            delta="Phase G metric"
            icon={Users}
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <h2 className="mb-2 text-[14px] font-semibold">Recent activity</h2>
            <div className="rounded-lg border border-[--color-border] bg-[--color-surface-1]">
              {auditEntries.length === 0 ? (
                <div className="px-4 py-6 text-center text-[12px] text-[--color-text-3]">
                  No audit events recorded yet.
                </div>
              ) : (
                <ul className="divide-y divide-[--color-border]">
                  {auditEntries.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex items-center gap-3 px-4 py-2.5 text-[13px]"
                    >
                      <StatusPill
                        status={
                          entry.action.includes("rejected")
                            ? "FAILED"
                            : entry.action.includes("review")
                              ? "MANUAL_REVIEW"
                              : "ACTIVE"
                        }
                        variant="dense"
                      />
                      <span className="flex-1 font-mono text-[12px]">
                        {entry.action}
                      </span>
                      <span className="text-[--color-text-3]">
                        {entry.actor_type} · {entry.actor_id.slice(0, 12)}…
                      </span>
                      <span className="w-[120px] text-right text-[11px] text-[--color-text-3]">
                        {formatTimestamp(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <div>
            <h2 className="mb-2 text-[14px] font-semibold">Alerts</h2>
            <div className="space-y-2">
              {manualReview.slice(0, 3).map((item) => (
                <Link
                  key={item.redemption_id}
                  href="/redemption"
                  className="block rounded-md border border-[--color-danger]/40 bg-[--color-danger]/10 px-3 py-2 text-[12px] text-[--color-danger]"
                >
                  <div className="font-semibold">Redemption manual review</div>
                  <div className="opacity-80">
                    <Coins className="mr-1 inline h-3 w-3" />
                    {item.amount} pts · retry {item.retry_count}
                  </div>
                </Link>
              ))}
              {manualReview.length === 0 && pending.length === 0 && (
                <div className="rounded-md border border-[--color-border] bg-[--color-surface-1] px-3 py-2 text-[12px] text-[--color-text-3]">
                  No alerts.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
