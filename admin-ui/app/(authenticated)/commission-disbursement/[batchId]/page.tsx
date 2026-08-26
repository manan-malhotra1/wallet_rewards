/**
 * Checker review screen for one disbursement batch.
 *
 * Shows each row's accrued balance, the amount being paid and the DELTA between
 * them, with the maker's note justifying it — the whole reason this screen
 * exists (spec §8.3). The balance is a snapshot taken at upload; the backend
 * re-checks it under a row lock at apply, so a stale one yields APPLIED_PARTIAL
 * rather than a wrong payment.
 */
import { notFound } from "next/navigation";

import { ApiError } from "@/lib/api";
import { getActiveTenant } from "@/lib/active-tenant";
import { getCommissionBatch } from "@/lib/api-endpoints";
import { batchTotals } from "@/lib/commission-batch";

import { BatchApprovalPanel } from "@/components/commission-batches/batch-approval-panel";
import { BatchRowTable } from "@/components/commission-batches/batch-row-table";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export const dynamic = "force-dynamic";

export default async function DisbursementBatchPage({
  params,
}: {
  params: Promise<{ batchId: string }>;
}) {
  const { batchId } = await params;
  const activeTenant = await getActiveTenant();
  if (!activeTenant) {
    return (
      <div className="p-6">
        <EmptyState title="No active tenant" />
      </div>
    );
  }

  let batch;
  try {
    batch = await getCommissionBatch(activeTenant.id, batchId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const totals = batchTotals(
    batch.rows.map((r) => ({
      status: r.status,
      amount: r.amount,
      balance_snapshot: r.balance_snapshot,
    })),
  );

  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title={batch.file_name}
        subtitle={`${totals.payable} of ${totals.rows} rows will pay · ${totals.amount.toFixed(2)} total · ${totals.heldBack.toFixed(2)} held back`}
      />

      <BatchApprovalPanel tenantId={activeTenant.id} batch={batch} />

      <BatchRowTable rows={batch.rows} />
    </div>
  );
}
