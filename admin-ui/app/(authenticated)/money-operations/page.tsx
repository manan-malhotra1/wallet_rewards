/**
 * Money-approvals review page (Epic 18 — N-eyes maker-checker for treasury
 * moves). The treasury approver's queue — defaults to PENDING (awaiting
 * approval); tabs expose CHANGES_REQUESTED / APPLIED / WITHDRAWN / all. Passes
 * the approver capability + current admin id down so the drawer can gate the
 * approve / request-changes / withdraw / revise actions.
 */
import Link from "next/link";
import { Landmark } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import { listMoneyOperations } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { MoneyOperation, MoneyOperationStatus } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { cn } from "@/lib/utils";

import { MoneyOperationsTable } from "./_components/money-operations-table";

export const dynamic = "force-dynamic";

/** Filter presets driving the status tab bar. `undefined` = all statuses. */
const FILTERS: { key: string; label: string; status?: MoneyOperationStatus }[] = [
  { key: "open", label: "Awaiting approval", status: "PENDING" },
  { key: "changes", label: "Changes requested", status: "CHANGES_REQUESTED" },
  { key: "applied", label: "Applied", status: "APPLIED" },
  { key: "withdrawn", label: "Withdrawn", status: "WITHDRAWN" },
  { key: "all", label: "All", status: undefined },
];

export default async function MoneyOperationsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status } = await searchParams;
  const activeFilter = FILTERS.find((f) => f.key === status) ?? FILTERS[0];

  const session = await auth();
  const canApprove =
    session?.user?.roles?.includes("treasury-approver") ?? false;
  const currentAdminId = session?.user?.id ?? "";

  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Landmark}
          title="No active tenant"
          description="Switch to a tenant to review its money operations."
        />
      </div>
    );
  }

  let operations: MoneyOperation[] = [];
  let error: ApiError | null = null;
  try {
    // The backend filters by a single status; pass the active tab's status
    // straight through (undefined = all).
    operations = await listMoneyOperations(activeTenantId, activeFilter.status);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Money approvals"
        subtitle="Review and approve proposed treasury money movements (N-eyes maker-checker)."
      />
      <div className="space-y-4 p-6">
        <nav className="flex flex-wrap gap-1">
          {FILTERS.map((f) => {
            const isActive = f.key === activeFilter.key;
            const href = f.key === "open" ? "/money-operations" : `?status=${f.key}`;
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
            title="Couldn't load money operations"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && operations.length === 0 ? (
          <EmptyState
            icon={Landmark}
            title="No operations in this view"
            description="Proposed treasury moves appear here for a treasury approver to review and approve."
          />
        ) : (
          !error && (
            <MoneyOperationsTable
              operations={operations}
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
