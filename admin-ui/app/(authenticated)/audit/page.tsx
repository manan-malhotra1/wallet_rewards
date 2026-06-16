/**
 * Audit log page — read-only, filterable by entity_type / entity_id.
 *
 * Drawer shows the before / after state JSON when an entry is clicked.
 * Phase G adds: full diff highlighting + CSV export + actor / date-range
 * filters.
 */
import { ShieldCheck } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { queryAuditLog } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { AuditFilters } from "./_components/audit-filters";
import { AuditTable } from "./_components/audit-table";

export const dynamic = "force-dynamic";

interface AuditPageProps {
  searchParams: Promise<{ entity_type?: string; entity_id?: string; limit?: string }>;
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

  let entries: Awaited<ReturnType<typeof queryAuditLog>> = [];
  let error: ApiError | null = null;
  try {
    entries = await queryAuditLog({
      tenant_id: activeTenantId,
      entity_type: params.entity_type || undefined,
      entity_id: params.entity_id || undefined,
      limit: params.limit ? Number(params.limit) : 100,
    });
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

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
      </div>
    </div>
  );
}
