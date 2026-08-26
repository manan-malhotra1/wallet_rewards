/**
 * /commission-disbursement — move accrued commission into earners' MAIN wallets.
 *
 * The counterpart menu, /commission-withdrawal, claws the same money back to an
 * operator bank mirror instead. They are deliberately two menus (spec D14):
 * different business acts, different reason codes, different destinations.
 */
import { HandCoins, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenant } from "@/lib/active-tenant";
import { listCommissionBatches } from "@/lib/api-endpoints";
import type { CommissionBatch } from "@/lib/api-types";

import { BatchList } from "@/components/commission-batches/batch-list";
import { UploadBatchDialog } from "@/components/commission-batches/upload-batch-dialog";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

export const dynamic = "force-dynamic";

export default async function CommissionDisbursementPage() {
  const activeTenant = await getActiveTenant();
  if (!activeTenant) {
    return (
      <div className="p-6">
        <EmptyState
          icon={HandCoins}
          title="No active tenant"
          description="Switch to a tenant to run a disbursement."
        />
      </div>
    );
  }

  let batches: CommissionBatch[] = [];
  let error: string | null = null;
  try {
    batches = await listCommissionBatches(activeTenant.id, {
      batch_type: "disbursement",
    });
  } catch (err) {
    error =
      err instanceof ApiError ? err.message : "Could not load disbursements.";
  }

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Commission disbursement"
        subtitle="Move accrued commission from commission wallets into earners' main wallets. Every run is four-eyes."
        actions={
          <UploadBatchDialog
            tenantId={activeTenant.id}
            batchType="disbursement"
            trigger={
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                New batch
              </Button>
            }
          />
        }
      />

      {error ? (
        <ErrorBanner title="Could not load disbursements" description={error} />
      ) : batches.length === 0 ? (
        <EmptyState
          icon={HandCoins}
          title="No disbursement batches yet"
          description="Upload a CSV of mobile number, currency and amount to start a run."
        />
      ) : (
        <BatchList batches={batches} basePath="/commission-disbursement" />
      )}
    </div>
  );
}
