/**
 * <WithdrawFromUserDialog> — admin pull-back form for the System Wallets page header.
 *
 * Mirror of FundUserDialog in the reverse direction: DEBIT user wallet,
 * CREDIT operator_adjustment. Target user is picked by registered
 * identifier (phone/email/account/card) — never a raw UUID. Admin
 * operations are PIN-less and fee-less.
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import type { TreasuryIdentifierType } from "@/lib/api-endpoints";
import type { SystemWallet } from "@/lib/api-types";

const IDENTIFIER_LABEL: Record<TreasuryIdentifierType, string> = {
  phone: "Phone",
  email: "Email",
  account_number: "Account",
  card_number: "Card",
};

const IDENTIFIER_PLACEHOLDER: Record<TreasuryIdentifierType, string> = {
  phone: "+27 82 555 0001",
  email: "user@example.com",
  account_number: "ZA-001-887-2210",
  card_number: "5234 5678 9012 3456",
};

interface FormState {
  identifier_type: TreasuryIdentifierType;
  identifier_value: string;
  amount: string;
  currency: string;
  reason: string;
  bank_mirror_account_id: string;
}

/** Fresh form seeded with the active tenant's currency (never a hardcoded "ZAR"). */
function initialState(defaultCurrency: string): FormState {
  return {
    identifier_type: "phone",
    identifier_value: "",
    amount: "",
    currency: defaultCurrency,
    reason: "",
    bank_mirror_account_id: "",
  };
}

export function WithdrawFromUserDialog({
  tenantId,
  defaultCurrency,
  mirrors,
  trigger,
}: {
  tenantId: string;
  /** The active tenant's base currency — the currency field's default. */
  defaultCurrency: string;
  /** Candidate bank-mirror counter-legs (all operator_adjustment wallets). */
  mirrors: SystemWallet[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() =>
    initialState(defaultCurrency),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Counter-leg must match the withdrawal currency.
  const eligibleMirrors = mirrors.filter(
    (m) => m.currency === form.currency.toUpperCase(),
  );

  React.useEffect(() => {
    if (!open) {
      setForm(initialState(defaultCurrency));
      setError(null);
    }
  }, [open, defaultCurrency]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  async function onSubmit() {
    setError(null);
    if (!form.identifier_value.trim()) {
      setError(`${IDENTIFIER_LABEL[form.identifier_type]} is required.`);
      return;
    }
    const n = Number(form.amount);
    if (!Number.isFinite(n) || n <= 0) {
      setError("Amount must be a positive number.");
      return;
    }
    if (!form.bank_mirror_account_id) {
      setError("Select a bank mirror for the counter-leg.");
      return;
    }
    if (!form.reason.trim()) {
      setError("Reason is required for the audit row.");
      return;
    }
    setSubmitting(true);
    const result = await withdrawFromUserAction({
      tenant_id: tenantId,
      identifier_type: form.identifier_type,
      identifier_value: form.identifier_value.trim(),
      amount: form.amount,
      currency: form.currency.toUpperCase(),
      reason: form.reason,
      bank_mirror_account_id: form.bank_mirror_account_id,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Proposed for approval", description: result.message });
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
            <Label>User identifier</Label>
            <div className="mt-1 grid grid-cols-[1fr_2fr] gap-2">
              <Select
                value={form.identifier_type}
                onValueChange={(v) =>
                  update("identifier_type", v as TreasuryIdentifierType)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="phone">Phone</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="account_number">Account</SelectItem>
                  <SelectItem value="card_number">Card</SelectItem>
                </SelectContent>
              </Select>
              <Input
                value={form.identifier_value}
                onChange={(e) => update("identifier_value", e.target.value)}
                placeholder={IDENTIFIER_PLACEHOLDER[form.identifier_type]}
              />
            </div>
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
                onChange={(e) => {
                  // Currency drives which mirrors are eligible — drop any
                  // now-ineligible selection so we never submit a mismatch.
                  update("currency", e.target.value);
                  update("bank_mirror_account_id", "");
                }}
                maxLength={10}
                className="mt-1 uppercase"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="w-mirror">Bank mirror (counter-leg)</Label>
            <Select
              value={form.bank_mirror_account_id}
              onValueChange={(v) => update("bank_mirror_account_id", v)}
            >
              <SelectTrigger id="w-mirror" className="mt-1">
                <SelectValue placeholder="Select a bank mirror…" />
              </SelectTrigger>
              <SelectContent>
                {eligibleMirrors.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name ?? "Bank Mirror"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {eligibleMirrors.length === 0 ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                No {form.currency.toUpperCase()} bank mirror available. Create one first.
              </p>
            ) : null}
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
