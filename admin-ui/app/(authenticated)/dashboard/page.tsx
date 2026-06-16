/**
 * Dashboard — single-glance health of the active tenant.
 */
import {
  ArrowUpRight,
  AlertTriangle,
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

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  icon: React.ComponentType<{ className?: string }>;
  href?: string;
  tone?: "neutral" | "warning" | "danger" | "success";
}

function KpiCard({ label, value, delta, icon: Icon, href, tone = "neutral" }: KpiCardProps) {
  const toneStripe =
    tone === "warning"
      ? "bg-amber-500"
      : tone === "danger"
        ? "bg-red-500"
        : tone === "success"
          ? "bg-emerald-500"
          : "bg-primary";
  const inner = (
    <Card className="relative overflow-hidden gap-3 py-5">
      <span className={`absolute left-0 top-0 h-full w-1 ${toneStripe}`} />
      <CardHeader className="px-5">
        <div className="flex items-start justify-between">
          <CardDescription className="text-[11px] font-semibold uppercase tracking-wider">
            {label}
          </CardDescription>
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="px-5">
        <div className="font-mono text-3xl font-semibold tracking-tight tabular text-foreground">
          {value}
        </div>
        {delta && (
          <div className="mt-1 text-xs text-muted-foreground">{delta}</div>
        )}
      </CardContent>
    </Card>
  );
  if (href) {
    return (
      <Link href={href} className="block transition-shadow hover:shadow-md">
        {inner}
      </Link>
    );
  }
  return inner;
}

export default async function DashboardPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
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

  const [pendingResult, manualResult, auditResult] = await Promise.allSettled([
    listPendingRedemptions(tenantId, 5),
    listManualReview(tenantId),
    queryAuditLog({ tenant_id: tenantId, limit: 10 }),
  ]);

  const pending = pendingResult.status === "fulfilled" ? pendingResult.value : [];
  const manualReview = manualResult.status === "fulfilled" ? manualResult.value : [];
  const auditEntries = auditResult.status === "fulfilled" ? auditResult.value : [];

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
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
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
            delta={manualReview.length > 0 ? "operator action required" : "queue empty"}
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
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">Recent activity</CardTitle>
              <CardDescription>Last 10 entries from the audit log.</CardDescription>
            </CardHeader>
            <CardContent>
              {auditEntries.length === 0 ? (
                <div className="rounded-md border border-dashed bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
                  No audit events recorded yet.
                </div>
              ) : (
                <ul className="divide-y">
                  {auditEntries.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex items-center gap-3 py-2.5 text-sm"
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
                      <span className="flex-1 font-mono text-xs text-foreground">
                        {entry.action}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {entry.actor_type} · {entry.actor_id.slice(0, 12)}…
                      </span>
                      <span className="w-[120px] text-right text-[11px] text-muted-foreground">
                        {formatTimestamp(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Alerts</CardTitle>
              <CardDescription>Items that need someone to look.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {manualReview.slice(0, 3).map((item) => (
                <Link
                  key={item.redemption_id}
                  href="/redemption"
                  className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive transition-colors hover:bg-destructive/10"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <div className="flex-1">
                    <div className="font-semibold">Redemption manual review</div>
                    <div className="text-xs opacity-80">
                      {item.amount} pts · retry {item.retry_count}
                    </div>
                  </div>
                  <ArrowUpRight className="h-3.5 w-3.5 shrink-0" />
                </Link>
              ))}
              {manualReview.length === 0 && pending.length === 0 && (
                <div className="rounded-md border border-dashed bg-muted/30 px-3 py-4 text-center text-xs text-muted-foreground">
                  No alerts.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
