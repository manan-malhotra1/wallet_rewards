/**
 * Pricing page — fixed + variable fee configs per (tenant, txn-type,
 * account-type, currency). Phase G.3 / WAL-52.
 */
import { Coins, Plus } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  getUserTypeCatalog,
  listConfigRequests,
  listInstruments,
  listPricingConfigs,
  listServices,
} from "@/lib/api-endpoints";
import { getActiveTenant } from "@/lib/active-tenant";
import { tenantHasRewards } from "@/lib/tenant-mode";
import type {
  ConfigChangeRequest,
  Instrument,
  Service,
  UserTypeCatalog,
} from "@/lib/api-types";
import { groupPricingConfigs } from "@/lib/config-groups";
import { changeProposedScopeKeys } from "@/lib/config-scope";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreatePricingDialog } from "./_components/create-pricing-dialog";
import { PricingChangesRequested } from "./_components/pricing-changes-requested";
import { PricingTable } from "./_components/pricing-table";

export const dynamic = "force-dynamic";

export default async function PricingPage() {
  const session = await auth();
  // Only platform-admins may propose config changes; the backend also 403s,
  // this just hides affordances that would fail for other admins.
  const canPropose = session?.user?.roles?.includes("platform-admin") ?? false;
  const currentAdminId = session?.user?.id ?? "";

  const activeTenant = await getActiveTenant();
  const activeTenantId = activeTenant?.id ?? null;
  // Points options only exist for a points programme (B6.1).
  const pointsAvailable = activeTenant ? tenantHasRewards(activeTenant.business_type) : false;
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Coins}
          title="No active tenant"
          description="Switch to a tenant to manage its pricing."
        />
      </div>
    );
  }

  let configs: Awaited<ReturnType<typeof listPricingConfigs>> = [];
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
      listPricingConfigs(activeTenantId),
      listServices(activeTenantId, "active"),
      listInstruments(activeTenantId, "active"),
      getUserTypeCatalog(activeTenantId),
      // All in-flight pricing proposals (both open statuses) so anyone can see
      // a change is under approval; actions on the card are maker-gated.
      listConfigRequests(activeTenantId, undefined, "pricing"),
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
        title="Service charges"
        subtitle="Fixed + variable fees per transaction type, by amount band."
        actions={
          canPropose ? (
            <CreatePricingDialog
              pointsAvailable={pointsAvailable}
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
                  New pricing
                </button>
              }
            />
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load pricing"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <PricingChangesRequested
              pointsAvailable={pointsAvailable}
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
            icon={Coins}
            title="No pricing configured"
            description="Per Pay-PRD-0420 every transaction MUST go through pricing. Add a config row (zero-fee is fine) per transaction type."
          />
        ) : (
          <PricingTable
              pointsAvailable={pointsAvailable}
            groups={groupPricingConfigs(configs)}
            tenantId={activeTenantId}
            services={services}
            instruments={instruments}
            catalog={catalog}
            canPropose={canPropose}
            serviceNames={Object.fromEntries(
              services.map((s) => [s.code, s.display_name]),
            )}
            changeProposedKeys={changeProposedScopeKeys(
              "pricing",
              openRequests,
              configs,
            )}
          />
        )}
      </div>
    </div>
  );
}
