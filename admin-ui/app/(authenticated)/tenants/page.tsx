/**
 * Tenants page — Phase 1 identity card.
 *
 * Lists every tenant as a stacked identity card. Name and business_type
 * are editable inline; tenant id, Keycloak realm, currency and status
 * are read-only. PATCH lands via the server action in `_actions.ts`.
 */
import { Plus, Settings2 } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import { listTenants } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateTenantDialog } from "./_components/create-tenant-dialog";
import { TenantCard } from "./_components/tenant-card";

const NEW_BUTTON_CLASS =
  "inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90";

export const dynamic = "force-dynamic";

export default async function TenantsPage() {
  const session = await auth();
  // Only platform-admins may edit a tenant's branding; the backend also 403s,
  // this just hides the affordance for other admins.
  const canManageBranding =
    session?.user?.roles?.includes("platform-admin") ?? false;

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
        actions={
          canManageBranding ? (
            <CreateTenantDialog
              trigger={
                <button type="button" className={NEW_BUTTON_CLASS}>
                  <Plus className="h-3.5 w-3.5" />
                  New tenant
                </button>
              }
            />
          ) : undefined
        }
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
            description="Create the first tenant with the New tenant button above."
          />
        ) : (
          tenants.map((tenant) => (
            <TenantCard
              key={tenant.id}
              tenant={tenant}
              canManageBranding={canManageBranding}
            />
          ))
        )}
      </div>
    </div>
  );
}
