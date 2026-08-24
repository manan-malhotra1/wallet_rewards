/**
 * Services catalog page — Phase 2 of the Tenant Management refactor.
 *
 * Lists every service (transaction type) registered for the active tenant.
 * The catalog is the source of truth for the Limits, Pricing, and
 * Campaigns dropdowns that replaced the old free-text inputs.
 */
import { Plus, Tag } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { getUserTypeCatalog, listServices } from "@/lib/api-endpoints";
import type { UserTypeCatalog } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateServiceDialog } from "./_components/create-service-dialog";
import { ServicesTable } from "./_components/services-table";

export const dynamic = "force-dynamic";

export default async function ServicesPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Tag}
          title="No active tenant"
          description="Switch to a tenant to manage its services catalog."
        />
      </div>
    );
  }

  let services: Awaited<ReturnType<typeof listServices>> = [];
  // The access policy is an allow-list of user-type codes, so the editor needs
  // the runtime catalog to offer options and to label the stored codes.
  let catalog: UserTypeCatalog = { categories: [], types: [] };
  let error: ApiError | null = null;
  try {
    [services, catalog] = await Promise.all([
      listServices(activeTenantId),
      getUserTypeCatalog(activeTenantId),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Services"
        subtitle="The transaction types this tenant has switched on. Platform services ship with the product; you can add named variants of them with their own pricing and limits."
        actions={
          <CreateServiceDialog
            tenantId={activeTenantId}
            services={services}
            catalog={catalog}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New service
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load services"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && services.length === 0 ? (
          <EmptyState
            icon={Tag}
            title="No services yet"
            description="The platform base services are provisioned with the tenant, so an empty catalog means provisioning hasn't run for this tenant yet."
          />
        ) : (
          <ServicesTable
            services={services}
            tenantId={activeTenantId}
            catalog={catalog}
          />
        )}
      </div>
    </div>
  );
}
