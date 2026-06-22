/**
 * Tenants page — Phase 1 identity card.
 *
 * Lists every tenant as a stacked identity card. Name and business_type
 * are editable inline; tenant id, Keycloak realm, currency and status
 * are read-only. PATCH lands via the server action in `_actions.ts`.
 */
import { Settings2 } from "lucide-react";

import { ApiError } from "@/lib/api";
import { listTenants } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { TenantCard } from "./_components/tenant-card";

export const dynamic = "force-dynamic";

export default async function TenantsPage() {
  let tenants: Awaited<ReturnType<typeof listTenants>> = [];
  let error: ApiError | null = null;
  try {
    tenants = await listTenants();
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Tenants"
        subtitle="Per-tenant identity. Edit name and business type; ID and Keycloak realm are managed elsewhere."
      />
      <div className="space-y-4 px-6 py-6">
        {error && (
          <ErrorBanner
            title="Couldn't load tenants"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && tenants.length === 0 ? (
          <EmptyState
            icon={Settings2}
            title="No tenants yet"
            description="Run the backend seed script to create the first tenant."
          />
        ) : (
          tenants.map((tenant) => <TenantCard key={tenant.id} tenant={tenant} />)
        )}
      </div>
    </div>
  );
}
