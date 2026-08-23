/**
 * Commissions page (Epic 24 / Story 24.2). Fixed + variable commission
 * (platform payout) per (tenant, txn-type, currency, user-type) with an
 * optional slab band. Writes flow through maker-checker.
 */
import { Percent, Plus } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  getUserTypeCatalog,
  listCommissionConfigs,
  listConfigRequests,
  listInstruments,
  listServices,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type {
  CommissionConfig,
  ConfigChangeRequest,
  Instrument,
  Service,
  UserTypeCatalog,
} from "@/lib/api-types";
import { groupCommissionConfigs } from "@/lib/config-groups";
import { changeProposedScopeKeys } from "@/lib/config-scope";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CommissionChangesRequested } from "./_components/commission-changes-requested";
import { CommissionTable } from "./_components/commission-table";
import { CreateCommissionDialog } from "./_components/create-commission-dialog";

export const dynamic = "force-dynamic";

export default async function CommissionsPage() {
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
          icon={Percent}
          title="No active tenant"
          description="Switch to a tenant to manage its commissions."
        />
      </div>
    );
  }

  let configs: CommissionConfig[] = [];
  let services: Service[] = [];
  let instruments: Instrument[] = [];
  // User types are runtime data, so the scope pickers and the type badges read
  // them from the catalog rather than a hardcoded list.
  let catalog: UserTypeCatalog = { categories: [], types: [] };
  let openRequests: ConfigChangeRequest[] = [];
  let error: ApiError | null = null;
  try {
    let requests: ConfigChangeRequest[] = [];
    [configs, services, instruments, catalog, requests] = await Promise.all([
      listCommissionConfigs(activeTenantId),
      listServices(activeTenantId, "active"),
      listInstruments(activeTenantId, "active"),
      getUserTypeCatalog(activeTenantId),
      // All in-flight commission proposals (both open statuses); card actions
      // are maker-gated.
      listConfigRequests(activeTenantId, undefined, "commission"),
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
        title="Commissions"
        subtitle="Agent/merchant payouts per transaction. Proposed changes require a second admin's approval."
        actions={
          canPropose ? (
            <CreateCommissionDialog
              tenantId={activeTenantId}
              services={services}
              instruments={instruments}
              catalog={catalog}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New commission
                </button>
              }
            />
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load commissions"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <CommissionChangesRequested
            requests={openRequests}
            tenantId={activeTenantId}
            currentAdminId={currentAdminId}
            services={services}
            instruments={instruments}
            catalog={catalog}
          />
        )}
        {!error && configs.length === 0 ? (
          <EmptyState
            icon={Percent}
            title="No commissions configured"
            description="Add a commission config to define agent/merchant payouts per transaction type."
          />
        ) : (
          <CommissionTable
            groups={groupCommissionConfigs(configs)}
            tenantId={activeTenantId}
            services={services}
            instruments={instruments}
            catalog={catalog}
            canPropose={canPropose}
            serviceNames={Object.fromEntries(
              services.map((s) => [s.code, s.display_name]),
            )}
            changeProposedKeys={changeProposedScopeKeys(
              "commission",
              openRequests,
              configs,
            )}
          />
        )}
      </div>
    </div>
  );
}
