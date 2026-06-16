"use client";

import * as React from "react";

import { createPricingConfigAction } from "@/app/(authenticated)/pricing/_actions";
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

interface FormState {
  transaction_type: string;
  account_type: string;
  currency: string;
  fixed_fee: string;
  variable_fee_pct: string;
  fee_cap: string;
}

const INITIAL: FormState = {
  transaction_type: "p2p",
  account_type: "financial_wallet",
  currency: "ZAR",
  fixed_fee: "0",
  variable_fee_pct: "0",
  fee_cap: "",
};

export function CreatePricingDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(INITIAL);
      setErrorBanner(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setErrorBanner(null);
    setSubmitting(true);
    const result = await createPricingConfigAction({
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      account_type: form.account_type,
      currency: form.currency.toUpperCase(),
      fixed_fee: form.fixed_fee || "0",
      variable_fee_pct: form.variable_fee_pct || "0",
      fee_cap: form.fee_cap || undefined,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Pricing created",
      description: `${form.transaction_type} · ${form.currency}`,
    });
    setOpen(false);
  };

  // Live fee preview helps operators sanity-check before saving.
  const preview = React.useMemo(() => {
    const amount = 1000;
    const fixed = parseFloat(form.fixed_fee) || 0;
    const pct = parseFloat(form.variable_fee_pct) || 0;
    const cap = form.fee_cap ? parseFloat(form.fee_cap) : Infinity;
    const variable = Math.min(pct * amount, cap);
    return (fixed + variable).toFixed(2);
  }, [form.fixed_fee, form.variable_fee_pct, form.fee_cap]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New pricing config</DialogTitle>
          <DialogDescription>
            Total fee = fixed + min(variable% × amount, fee cap).
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="txn">Txn type</Label>
              <Input
                id="txn"
                value={form.transaction_type}
                onChange={(e) => update("transaction_type", e.target.value)}
                placeholder="p2p"
              />
            </div>
            <div>
              <Label htmlFor="acct">Account type</Label>
              <Select
                value={form.account_type}
                onValueChange={(v) => update("account_type", v)}
              >
                <SelectTrigger id="acct">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="financial_wallet">Wallet</SelectItem>
                  <SelectItem value="points_account">Points</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="ccy">Currency</Label>
              <Input
                id="ccy"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={3}
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="fixed">Fixed fee</Label>
              <Input
                id="fixed"
                value={form.fixed_fee}
                onChange={(e) => update("fixed_fee", e.target.value)}
                placeholder="5"
              />
            </div>
            <div>
              <Label htmlFor="varpct">Variable %</Label>
              <Input
                id="varpct"
                value={form.variable_fee_pct}
                onChange={(e) => update("variable_fee_pct", e.target.value)}
                placeholder="0.025"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                As a decimal: 0.025 = 2.5%
              </p>
            </div>
            <div>
              <Label htmlFor="cap">Fee cap (optional)</Label>
              <Input
                id="cap"
                value={form.fee_cap}
                onChange={(e) => update("fee_cap", e.target.value)}
                placeholder="50"
              />
            </div>
          </div>
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            On a sample R 1000 transaction, the fee would be{" "}
            <span className="font-mono text-foreground">{preview}</span>.
          </div>
          {errorBanner && <ErrorBanner title="Couldn't create" description={errorBanner} />}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
