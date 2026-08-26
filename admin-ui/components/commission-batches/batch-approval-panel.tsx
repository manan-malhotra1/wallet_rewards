"use client";

/**
 * Approve or reject-whole-batch (checker), shared by both menus.
 *
 * Rejection is TERMINAL by design (spec D16): there is no revise-in-place loop,
 * so the comment is mandatory — it is the only thing the maker gets to work
 * from when they rebuild the file.
 */
import * as React from "react";
import { useRouter } from "next/navigation";

import type { CommissionBatch } from "@/lib/api-types";
import { batchStatusLabel, isTerminal } from "@/lib/commission-batch";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import {
  approveCommissionBatchAction,
  rejectCommissionBatchAction,
} from "@/app/(authenticated)/commission-batches-shared/actions";

/** Badge tone per batch status — a partial apply must not read as success. */
function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "APPLIED") return "success";
  if (status === "APPLIED_PARTIAL") return "warning";
  if (status === "REJECTED" || status === "WITHDRAWN") return "destructive";
  return "secondary";
}

export function BatchApprovalPanel({
  tenantId,
  batch,
}: {
  tenantId: string;
  batch: CommissionBatch;
}) {
  const router = useRouter();
  const [comment, setComment] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const terminal = isTerminal(batch.status);

  const onApprove = async () => {
    setBusy(true);
    setError(null);
    const outcome = await approveCommissionBatchAction(tenantId, batch.id);
    setBusy(false);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    router.refresh();
  };

  const onReject = async () => {
    if (!comment.trim()) {
      setError("Say what needs fixing — the maker rebuilds the file from this.");
      return;
    }
    setBusy(true);
    setError(null);
    const outcome = await rejectCommissionBatchAction(
      tenantId,
      batch.id,
      comment,
    );
    setBusy(false);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    router.refresh();
  };

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Approval</p>
          <p className="text-muted-foreground text-xs">
            {batch.approvals_received} of {batch.required_approvals} approval
            {batch.required_approvals === 1 ? "" : "s"} received
          </p>
        </div>
        <Badge variant={statusVariant(batch.status)} data-testid="batch-status">
          {batchStatusLabel(batch.status)}
        </Badge>
      </div>

      {error ? <ErrorBanner title="Could not action this batch" description={error} /> : null}

      {terminal ? (
        <p className="text-muted-foreground text-sm">
          {batch.status === "REJECTED"
            ? "This batch was rejected. The maker uploads a corrected file as a new batch."
            : "This batch has been applied and can no longer be actioned."}
        </p>
      ) : (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="reject-comment">Rejection reason</Label>
            <Textarea
              id="reject-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Required only when rejecting."
              rows={2}
            />
          </div>
          <div className="flex gap-2">
            <Button type="button" onClick={onApprove} disabled={busy}>
              {busy ? "Working…" : "Approve"}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={onReject}
              disabled={busy}
            >
              Reject batch
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            Rejection applies to the whole batch and cannot be undone.
          </p>
        </>
      )}
    </div>
  );
}
