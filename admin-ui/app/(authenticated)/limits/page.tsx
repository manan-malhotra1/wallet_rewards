/**
 * Limits page — per-(tenant, txn-type, account-type, currency) min/max
 * + rolling-24h count + value caps (Phase G.2 / WAL-51).
 */
import { ListChecks, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { listInstruments, listLimitConfigs, listServices } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { Instrument, Service } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateLimitDialog } from "./_components/create-limit-dialog";
import { LimitsTable } from "./_components/limits-table";

export const dynamic = "force-dynamic";

export default async function LimitsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={ListChecks}
          title="No active tenant"
          description="Switch to a tenant to manage its limits."
        />
      </div>
    );
  }

  let configs: Awaited<ReturnType<typeof listLimitConfigs>> = [];
  let services: Service[] = [];
  let instruments: Instrument[] = [];
  let error: ApiError | null = null;
  try {
    [configs, services, instruments] = await Promise.all([
      listLimitConfigs(activeTenantId),
      listServices(activeTenantId, "active"),
      listInstruments(activeTenantId, "active"),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Limits"
        subtitle="Min / max amounts and rolling-24h caps per transaction type. Step 2 of payment orchestration."
        actions={
          <CreateLimitDialog
            tenantId={activeTenantId}
            services={services}
            instruments={instruments}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New limit
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load limits"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && configs.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title="No limits configured"
            description="Without a config the orchestration silently allows any amount. Create the first one to bound user activity."
          />
        ) : (
          <LimitsTable configs={configs} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
