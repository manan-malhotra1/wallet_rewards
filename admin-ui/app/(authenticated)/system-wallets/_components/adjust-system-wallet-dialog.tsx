/**
 * <AdjustSystemWalletDialog> — fund (positive) or withdraw (negative)
 * a system wallet. The counter-leg lands on the per-tenant
 * operator_adjustment account so the ledger stays balanced.
 *
 * UI affordance: a Fund/Withdraw segmented control + a magnitude
 * input. Submitting flips the sign appropriately before sending.
 */
"use client";

import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";
import * as React from "react";

import { adjustSystemWalletAction } from "@/app/(authenticated)/system-wallets/_actions";
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
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import type { SystemWallet } from "@/lib/api-types";

type Direction = "fund" | "withdraw";

export function AdjustSystemWalletDialog({
  account,
  tenantId,
  trigger,
}: {
  account: SystemWallet;
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [direction, setDirection] = React.useState<Direction>("fund");
  const [magnitude, setMagnitude] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setDirection("fund");
      setMagnitude("");
      setReason("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  const onSubmit = async () => {
    setError(null);
    const n = Number(magnitude);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Amount must be a positive number.");
      return;
    }
    if (!reason.trim()) {
      setError("Reason is required for the audit row.");
      return;
    }
    const signed = direction === "fund" ? magnitude : `-${magnitude}`;
    setSubmitting(true);
    const result = await adjustSystemWalletAction({
      tenant_id: tenantId,
      account_id: account.id,
      amount: signed,
      reason,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Adjustment posted", description: result.message });
      setOpen(false);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Adjust system wallet</DialogTitle>
          <DialogDescription>
            Posts a balanced ledger transaction against operator_adjustment.
            Funding raises the balance; withdrawing lowers it.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 rounded-md bg-muted/40 p-1">
            <button
              type="button"
              onClick={() => setDirection("fund")}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition",
                direction === "fund"
                  ? "bg-emerald-500 text-white shadow"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
              Fund
            </button>
            <button
              type="button"
              onClick={() => setDirection("withdraw")}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition",
                direction === "withdraw"
                  ? "bg-rose-500 text-white shadow"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <ArrowUpFromLine className="h-3.5 w-3.5" />
              Withdraw
            </button>
          </div>
          <div>
            <Label htmlFor="magnitude">Amount ({account.currency})</Label>
            <Input
              id="magnitude"
              type="number"
              step="0.01"
              min="0.01"
              value={magnitude}
              onChange={(e) => setMagnitude(e.target.value)}
              placeholder="1000000"
              className="mt-1 tabular-nums"
            />
            <p className="mt-1 text-[11px] text-muted-foreground">
              Current balance: {account.balance} {account.currency}
            </p>
          </div>
          <div>
            <Label htmlFor="reason">Reason (audit)</Label>
            <textarea
              id="reason"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                direction === "fund"
                  ? "Initial float — Standard Bank wire reference 8023"
                  : "Ops expense — server bill, Q3"
              }
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          {error && <ErrorBanner title="Couldn't adjust" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting
              ? "Posting…"
              : direction === "fund"
                ? "Fund wallet"
                : "Withdraw"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
