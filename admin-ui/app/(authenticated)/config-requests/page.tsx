/**
 * Config-requests review page (Epic 24 / Story 24.3). Lists maker-checker
 * change requests with a status filter (default: open = PENDING +
 * CHANGES_REQUESTED). Passes approver capability + the current admin id down
 * so the drawer can gate checker vs. maker actions.
 */
import Link from "next/link";
import { GitPullRequest } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import { listConfigRequests } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { ConfigChangeRequest, ConfigRequestStatus } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { cn } from "@/lib/utils";

import { ConfigRequestsTable } from "./_components/config-requests-table";

export const dynamic = "force-dynamic";

/** Filter presets driving the status tab bar. `undefined` = all statuses. */
const FILTERS: { key: string; label: string; statuses?: ConfigRequestStatus[] }[] =
  [
    { key: "open", label: "Open", statuses: ["PENDING", "CHANGES_REQUESTED"] },
    { key: "pending", label: "Pending", statuses: ["PENDING"] },
    {
      key: "changes",
      label: "Changes requested",
      statuses: ["CHANGES_REQUESTED"],
    },
    { key: "applied", label: "Applied", statuses: ["APPLIED"] },
    { key: "withdrawn", label: "Withdrawn", statuses: ["WITHDRAWN"] },
    { key: "all", label: "All", statuses: undefined },
  ];

export default async function ConfigRequestsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const activeFilter = FILTERS.find((f) => f.key === status) ?? FILTERS[0];

  const session = await auth();
  const canApprove = session?.user?.roles?.includes("config-approver") ?? false;
  const currentAdminId = session?.user?.id ?? "";

  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={GitPullRequest}
          title="No active tenant"
          description="Switch to a tenant to review its config requests."
        />
      </div>
    );
  }

  let requests: ConfigChangeRequest[] = [];
  let error: ApiError | null = null;
  try {
    // Fetch all, then filter in-memory: the "Open" default spans two statuses,
    // which the single-status backend filter can't express in one call.
    requests = await listConfigRequests(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  const visible = activeFilter.statuses
    ? requests.filter((r) => activeFilter.statuses!.includes(r.status))
    : requests;

  return (
    <div>
      <PageHeader
        title="Config requests"
        subtitle="Review and approve proposed pricing, commission, tax, and limit changes (maker-checker)."
      />
      <div className="space-y-4 p-6">
        <nav className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const isActive = f.key === activeFilter.key;
            const href = f.key === "open" ? "/config-requests" : `?status=${f.key}`;
            return (
              <Link
                key={f.key}
                href={href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {f.label}
              </Link>
            );
          })}
        </nav>
        {error && (
          <ErrorBanner
            title="Couldn't load config requests"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && visible.length === 0 ? (
          <EmptyState
            icon={GitPullRequest}
            title="No requests in this view"
            description="Proposed config changes appear here for a second admin to review and approve."
          />
        ) : (
          !error && (
            <ConfigRequestsTable
              requests={visible}
              tenantId={activeTenantId}
              canApprove={canApprove}
              currentAdminId={currentAdminId}
            />
          )
        )}
      </div>
    </div>
  );
}
