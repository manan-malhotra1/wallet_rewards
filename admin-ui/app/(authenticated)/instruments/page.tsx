/**
 * Instruments catalog page — Phase 3 of the Tenant Management refactor.
 *
 * Lists every value unit (currency or points) registered for the active
 * tenant. ZAR and PTS are auto-seeded; tenants can add more (10-char
 * codes) and optionally backfill accounts for existing users on create.
 */
import { Plus, Ticket } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listInstruments } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateInstrumentDialog } from "./_components/create-instrument-dialog";
import { InstrumentsTable } from "./_components/instruments-table";

export const dynamic = "force-dynamic";

export default async function InstrumentsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Ticket}
          title="No active tenant"
          description="Switch to a tenant to manage its instruments catalog."
        />
      </div>
    );
  }

  let instruments: Awaited<ReturnType<typeof listInstruments>> = [];
  let error: ApiError | null = null;
  try {
    instruments = await listInstruments(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Instruments"
        subtitle="The value units (currencies and points) this tenant uses. Powers the currency dropdowns on Limits and Pricing."
        actions={
          <CreateInstrumentDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New instrument
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load instruments"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && instruments.length === 0 ? (
          <EmptyState
            icon={Ticket}
            title="No instruments yet"
            description="Add an instrument to populate the currency dropdowns on Limits and Pricing. The baseline (ZAR, PTS) is auto-seeded on a fresh database."
          />
        ) : (
          <InstrumentsTable instruments={instruments} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
