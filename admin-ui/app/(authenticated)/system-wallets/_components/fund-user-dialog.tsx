/**
 * <FundUserDialog> — admin fund form for the System Wallets page header.
 *
 * The target user is picked by registered identifier (phone, email,
 * account_number, card_number) — operators never type a UUID. The
 * backend resolves identifier → user_id via identity.resolve_identifier.
 * Submits via fundUserAction which wraps fund() (DEBIT
 * system_cash_inflow, CREDIT user_wallet).
 */
"use client";

import * as React from "react";

import { fundUserAction } from "@/app/(authenticated)/system-wallets/_actions";
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
}

const INITIAL: FormState = {
  identifier_type: "phone",
  identifier_value: "",
  amount: "",
  currency: "ZAR",
  reason: "",
};

export function FundUserDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(INITIAL);
      setError(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
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
    if (!form.reason.trim()) {
      setError("Reason is required for the audit row.");
      return;
    }
    setSubmitting(true);
    const result = await fundUserAction({
      tenant_id: tenantId,
      identifier_type: form.identifier_type,
      identifier_value: form.identifier_value.trim(),
      amount: form.amount,
      currency: form.currency.toUpperCase(),
      reason: form.reason,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "User funded", description: result.message });
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
          <DialogTitle>Fund a user wallet</DialogTitle>
          <DialogDescription>
            Credits the user's wallet and debits the tenant's system_cash_inflow.
            Audit row recorded.
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
              <Label htmlFor="amount">Amount</Label>
              <Input
                id="amount"
                type="number"
                step="0.01"
                min="0.01"
                value={form.amount}
                onChange={(e) => update("amount", e.target.value)}
                placeholder="500"
                className="mt-1 tabular-nums"
              />
            </div>
            <div>
              <Label htmlFor="currency">Currency</Label>
              <Input
                id="currency"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={10}
                className="mt-1 uppercase"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="reason">Reason (audit)</Label>
            <textarea
              id="reason"
              rows={2}
              value={form.reason}
              onChange={(e) => update("reason", e.target.value)}
              placeholder="Refund — failed fund #1234"
              className="mt-1 w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
          {error && <ErrorBanner title="Couldn't fund" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Funding…" : "Fund user"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
