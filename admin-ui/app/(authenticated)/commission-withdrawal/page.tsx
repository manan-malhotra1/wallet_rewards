/**
 * /commission-withdrawal — claw accrued commission back to an operator account.
 *
 * The counterpart menu, /commission-disbursement, pays the same money out to the
 * earner instead. They are deliberately two menus (spec D14): different
 * business acts, different reason codes, different destinations.
 */
import { Undo2, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenant } from "@/lib/active-tenant";
import { listCommissionBatches, listSystemWallets } from "@/lib/api-endpoints";
import type { CommissionBatch } from "@/lib/api-types";

import { BatchList } from "@/components/commission-batches/batch-list";
import { UploadBatchDialog } from "@/components/commission-batches/upload-batch-dialog";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

export const dynamic = "force-dynamic";

export default async function CommissionWithdrawalPage() {
  const activeTenant = await getActiveTenant();
  if (!activeTenant) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Undo2}
          title="No active tenant"
          description="Switch to a tenant to run a clawback."
        />
      </div>
    );
  }

  let batches: CommissionBatch[] = [];
  let bankMirrors: { id: string; label: string }[] = [];
  let error: string | null = null;
  try {
    batches = await listCommissionBatches(activeTenant.id, {
      batch_type: "withdrawal",
    });
    // Only named bank mirrors may receive a clawback — the money leaves the
    // platform, so it must land in a real operator account.
    const wallets = await listSystemWallets(activeTenant.id);
    bankMirrors = wallets
      .filter((w) => w.account_type === "operator_adjustment")
      .map((w) => ({
        id: w.id,
        label: `${w.name ?? "Bank mirror"} (${w.currency})`,
      }));
  } catch (err) {
    error =
      err instanceof ApiError ? err.message : "Could not load withdrawals.";
  }

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Commission withdrawal"
        subtitle="Claw incorrectly accrued commission back from commission wallets into an operator account. Every run is four-eyes."
        actions={
          <UploadBatchDialog
            tenantId={activeTenant.id}
            batchType="withdrawal"
            bankMirrors={bankMirrors}
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
        <ErrorBanner title="Could not load withdrawals" description={error} />
      ) : batches.length === 0 ? (
        <EmptyState
          icon={Undo2}
          title="No withdrawal batches yet"
          description="Upload a CSV of mobile number, currency and amount to claw commission back."
        />
      ) : (
        <BatchList batches={batches} basePath="/commission-withdrawal" />
      )}
    </div>
  );
}
