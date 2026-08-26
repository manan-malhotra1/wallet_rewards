"use client";

/**
 * Upload a commission batch CSV (maker), shared by both menus.
 *
 * After a successful upload the dialog shows the VALIDATION SUMMARY rather than
 * closing: the maker needs to see how many rows will actually pay, and download
 * the rejects, before a checker ever looks at it (spec §8.2).
 */
import * as React from "react";

import type { CommissionBatch, CommissionBatchType } from "@/lib/api-types";
import { rejectReasonLabel } from "@/lib/commission-batch";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  fetchCommissionBatchRejectsAction,
  uploadCommissionBatchAction,
} from "@/app/(authenticated)/commission-batches-shared/actions";

/** A named operator_adjustment account a withdrawal can land in. */
export interface BankMirrorOption {
  id: string;
  label: string;
}

interface Props {
  tenantId: string;
  batchType: CommissionBatchType;
  /** Withdrawal only — a destination is required, disbursement derives its own. */
  bankMirrors?: BankMirrorOption[];
  trigger: React.ReactNode;
}

export function UploadBatchDialog({
  tenantId,
  batchType,
  bankMirrors = [],
  trigger,
}: Props) {
  const [open, setOpen] = React.useState(false);
  const [file, setFile] = React.useState<File | null>(null);
  const [mirrorId, setMirrorId] = React.useState<string>("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<CommissionBatch | null>(null);

  const isWithdrawal = batchType === "withdrawal";
  const canSubmit = file != null && (!isWithdrawal || mirrorId !== "");

  const reset = () => {
    setFile(null);
    setMirrorId("");
    setError(null);
    setResult(null);
  };

  const onSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    setError(null);

    const form = new FormData();
    form.set("batch_type", batchType);
    form.set("file", file);
    if (isWithdrawal && mirrorId) {
      form.set("destination_account_id", mirrorId);
    }

    const outcome = await uploadCommissionBatchAction(tenantId, form);
    setSubmitting(false);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    setResult(outcome.data);
  };

  const downloadRejects = async () => {
    if (!result) return;
    const outcome = await fetchCommissionBatchRejectsAction(tenantId, result.id);
    if (!outcome.ok) {
      setError(outcome.message);
      return;
    }
    // A blob URL keeps the CSV entirely client-side — the file never needs a
    // second authenticated round trip to be saved.
    const blob = new Blob([outcome.data], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `rejects-${result.id}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const rejectedCount = result
    ? result.row_count_total - result.row_count_valid
    : 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isWithdrawal ? "New withdrawal batch" : "New disbursement batch"}
          </DialogTitle>
          <DialogDescription>
            CSV with columns <code>msisdn, currency, amount, note</code>.
            Currency is required — a user may hold several commission wallets.
          </DialogDescription>
        </DialogHeader>

        {error ? <ErrorBanner title="Upload failed" description={error} /> : null}

        {result ? (
          <div className="space-y-3" data-testid="upload-summary">
            <p className="text-sm">
              <span className="font-semibold">{result.row_count_valid}</span> of{" "}
              <span className="font-semibold">{result.row_count_total}</span>{" "}
              rows will pay, totalling{" "}
              <span className="font-semibold">{result.amount_total}</span>.
            </p>
            {rejectedCount > 0 ? (
              <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
                <p className="text-sm">
                  {rejectedCount} row{rejectedCount === 1 ? "" : "s"} could not
                  be paid and {rejectedCount === 1 ? "was" : "were"} left out.
                  Fix them and upload a new batch.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={downloadRejects}
                >
                  Download rejected rows
                </Button>
              </div>
            ) : (
              <p className="text-sm text-emerald-700 dark:text-emerald-300">
                Every row passed validation.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {isWithdrawal ? (
              <div className="space-y-1.5">
                <Label htmlFor="batch-mirror">Destination bank mirror</Label>
                <Select value={mirrorId} onValueChange={setMirrorId}>
                  <SelectTrigger id="batch-mirror">
                    <SelectValue placeholder="Choose an account" />
                  </SelectTrigger>
                  <SelectContent>
                    {bankMirrors.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">
                  Clawed-back commission lands here, not in the user&apos;s
                  wallet.
                </p>
              </div>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="batch-file">CSV file</Label>
              <Input
                id="batch-file"
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          </div>
        )}

        <DialogFooter>
          {result ? (
            <Button type="button" onClick={() => setOpen(false)}>
              Done
            </Button>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="button" onClick={onSubmit} disabled={!canSubmit || submitting}>
                {submitting ? "Uploading…" : "Upload"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Re-exported so a route can render a reason without importing the lib. */
export { rejectReasonLabel };
