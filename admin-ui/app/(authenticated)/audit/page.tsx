/**
 * Audit log page — read-only, filterable by entity_type / entity_id.
 *
 * Drawer shows the before / after state JSON when an entry is clicked.
 * Phase G adds: full diff highlighting + CSV export + actor / date-range
 * filters.
 */
import { ShieldCheck } from "lucide-react";
import Link from "next/link";

import { getActiveTenantId } from "@/lib/active-tenant";
import { queryAuditLog } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { AuditFilters } from "./_components/audit-filters";
import { AuditTable } from "./_components/audit-table";

export const dynamic = "force-dynamic";

/** Rows fetched per page — the log grows for 7 years, so views page (B7.3). */
const AUDIT_PAGE_SIZE = 100;

interface AuditPageProps {
  searchParams: Promise<{
    entity_type?: string;
    entity_id?: string;
    limit?: string;
    page?: string;
  }>;
}

export default async function AuditPage({ searchParams }: AuditPageProps) {
  const params = await searchParams;
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={ShieldCheck}
          title="No active tenant"
          description="Switch to a tenant to view its audit log."
        />
      </div>
    );
  }

  const requestedPage = Number(params.page);
  const page = Number.isInteger(requestedPage) && requestedPage >= 1 ? requestedPage : 1;
  const limit = params.limit ? Number(params.limit) : AUDIT_PAGE_SIZE;

  let entries: Awaited<ReturnType<typeof queryAuditLog>> = [];
  let error: ApiError | null = null;
  try {
    entries = await queryAuditLog({
      tenant_id: activeTenantId,
      entity_type: params.entity_type || undefined,
      entity_id: params.entity_id || undefined,
      limit,
      offset: (page - 1) * limit,
    });
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // Blind pager (the log has no counts endpoint): a full window means there
  // may be more, so offer Next; Previous appears whenever we're past page 1.
  const pageHref = (target: number) => {
    const sp = new URLSearchParams();
    if (params.entity_type) sp.set("entity_type", params.entity_type);
    if (params.entity_id) sp.set("entity_id", params.entity_id);
    if (target > 1) sp.set("page", String(target));
    const qs = sp.toString();
    return qs ? `/audit?${qs}` : "/audit";
  };
  const hasPrevious = page > 1;
  const hasNext = entries.length === limit;

  return (
    <div>
      <PageHeader
        title="Audit log"
        subtitle="Every state-changing admin + system action is recorded here. Immutable 7-year retention."
      />
      <div className="px-6 py-6">
        <AuditFilters
          initialEntityType={params.entity_type ?? ""}
          initialEntityId={params.entity_id ?? ""}
        />
        <div className="mt-4">
          {error && (
            <ErrorBanner
              title="Couldn't load audit log"
              description={`${error.errorCode}: ${error.message}`}
            />
          )}
          {!error && entries.length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              title="No audit entries"
              description="Either nothing has been done yet, or your filters excluded everything."
            />
          ) : (
            <AuditTable entries={entries} />
          )}
        </div>
        {!error && (hasPrevious || hasNext) && (
          <div className="mt-4 flex items-center justify-end gap-3 text-sm">
            {hasPrevious && (
              <Link href={pageHref(page - 1)} className="text-muted-foreground hover:text-foreground">
                ← Previous
              </Link>
            )}
            <span className="text-xs text-muted-foreground tabular-nums">Page {page}</span>
            {hasNext && (
              <Link href={pageHref(page + 1)} className="text-muted-foreground hover:text-foreground">
                Next →
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
