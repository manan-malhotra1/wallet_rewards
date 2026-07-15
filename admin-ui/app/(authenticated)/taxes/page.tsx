/**
 * Taxes page (Epic 24 / Story 24.2). One tax config per (tenant, currency),
 * applying fee + commission tax rates independently. Writes flow through
 * maker-checker.
 */
import { Plus, Receipt } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  listConfigRequests,
  listInstruments,
  listTaxConfigs,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { ConfigChangeRequest, Instrument, TaxConfig } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateTaxDialog } from "./_components/create-tax-dialog";
import { TaxChangesRequested } from "./_components/tax-changes-requested";
import { TaxTable } from "./_components/tax-table";

export const dynamic = "force-dynamic";

export default async function TaxesPage() {
  const session = await auth();
  // Only platform-admins may propose config changes; the backend also 403s,
  // this just hides affordances that would fail for other admins.
  const canPropose = session?.user?.roles?.includes("platform-admin") ?? false;
  const currentAdminId = session?.user?.id ?? "";

  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Receipt}
          title="No active tenant"
          description="Switch to a tenant to manage its taxes."
        />
      </div>
    );
  }

  let configs: TaxConfig[] = [];
  let instruments: Instrument[] = [];
  let openRequests: ConfigChangeRequest[] = [];
  let error: ApiError | null = null;
  try {
    let requests: ConfigChangeRequest[] = [];
    [configs, instruments, requests] = await Promise.all([
      listTaxConfigs(activeTenantId),
      listInstruments(activeTenantId, "active"),
      // All in-flight tax proposals (both open statuses); card actions are
      // maker-gated.
      listConfigRequests(activeTenantId, undefined, "tax"),
    ]);
    openRequests = requests.filter(
      (r) => r.status === "PENDING" || r.status === "CHANGES_REQUESTED",
    );
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Taxes"
        subtitle="Fee + commission tax per currency. Proposed changes require a second admin's approval."
        actions={
          canPropose ? (
            <CreateTaxDialog
              tenantId={activeTenantId}
              instruments={instruments}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New tax
                </button>
              }
            />
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load taxes"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <TaxChangesRequested
            requests={openRequests}
            tenantId={activeTenantId}
            currentAdminId={currentAdminId}
            instruments={instruments}
          />
        )}
        {!error && configs.length === 0 ? (
          <EmptyState
            icon={Receipt}
            title="No taxes configured"
            description="Add a tax config per currency to apply fee and commission tax rates."
          />
        ) : (
          <TaxTable
            configs={configs}
            tenantId={activeTenantId}
            instruments={instruments}
            canPropose={canPropose}
          />
        )}
      </div>
    </div>
  );
}
