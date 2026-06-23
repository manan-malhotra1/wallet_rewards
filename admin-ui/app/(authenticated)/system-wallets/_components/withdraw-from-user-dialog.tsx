/**
 * <WithdrawFromUserDialog> — admin pull-back form for the System Wallets page header.
 *
 * Mirrors FundUserDialog but in reverse: DEBIT user wallet, CREDIT
 * operator_adjustment. Admin operations are PIN-less (operator's
 * Keycloak session is the only authentication) and fee-less.
 */
"use client";

import * as React from "react";

import { withdrawFromUserAction } from "@/app/(authenticated)/system-wallets/_actions";
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

interface FormState {
  user_id: string;
  amount: string;
  currency: string;
  reason: string;
}

const INITIAL: FormState = {
  user_id: "",
  amount: "",
  currency: "ZAR",
  reason: "",
};

export function WithdrawFromUserDialog({
  tenantId,
  defaultUserId,
  trigger,
}: {
  tenantId: string;
  defaultUserId?: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>({
    ...INITIAL,
    user_id: defaultUserId ?? "",
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm({ ...INITIAL, user_id: defaultUserId ?? "" });
      setError(null);
    }
  }, [open, defaultUserId]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  async function onSubmit() {
    setError(null);
    if (!form.user_id) {
      setError("user_id is required.");
      return;
    }
    const n = Number(form.amount);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Amount must be a positive number.");
      return;
    }
    if (!form.reason.trim()) {
      setError("Reason is required for the audit row.");
      return;
    }

    setSubmitting(true);
    const result = await withdrawFromUserAction({
      tenant_id: tenantId,
      user_id: form.user_id,
      amount: form.amount,
      currency: form.currency.toUpperCase(),
      reason: form.reason,
    });
    setSubmitting(false);

    if (result.ok) {
      toast({ title: "Withdraw posted", description: result.message });
      setOpen(false);
      return;
    }
    setError(`${result.errorCode}: ${result.message}`);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Withdraw from a user wallet</DialogTitle>
          <DialogDescription>
            Debits the user's wallet and credits operator_adjustment.
            Admin operations are PIN-less — your operator session is the
            authentication.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="w-user-id">User ID</Label>
            <Input
              id="w-user-id"
              value={form.user_id}
              onChange={(e) => update("user_id", e.target.value)}
              placeholder="00000000-0000-…"
              className="mt-1 font-mono text-xs"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="w-amount">Amount</Label>
              <Input
                id="w-amount"
                type="number"
                step="0.01"
                min="0.01"
                value={form.amount}
                onChange={(e) => update("amount", e.target.value)}
                placeholder="200"
                className="mt-1 tabular-nums"
              />
            </div>
            <div>
              <Label htmlFor="w-currency">Currency</Label>
              <Input
                id="w-currency"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={10}
                className="mt-1 uppercase"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="w-reason">Reason (audit)</Label>
            <textarea
              id="w-reason"
              rows={2}
              value={form.reason}
              onChange={(e) => update("reason", e.target.value)}
              placeholder="Cash-out at agent counter."
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          {error && <ErrorBanner title="Couldn't withdraw" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Withdrawing…" : "Withdraw"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
