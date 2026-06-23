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
import type { Instrument, Service } from "@/lib/api-types";

interface FormState {
  transaction_type: string;
  account_type: string;
  currency: string;
  fixed_fee: string;
  variable_fee_pct: string;
  fee_cap: string;
}

function initialForm(services: Service[], instruments: Instrument[]): FormState {
  return {
    transaction_type: services[0]?.code ?? "",
    account_type: "financial_wallet",
    currency:
      instruments.find((i) => i.account_type === "financial_wallet")?.code ??
      instruments[0]?.code ??
      "",
    fixed_fee: "0",
    variable_fee_pct: "0",
    fee_cap: "",
  };
}

export function CreatePricingDialog({
  tenantId,
  services,
  instruments,
  trigger,
}: {
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() =>
    initialForm(services, instruments),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(services, instruments));
      setErrorBanner(null);
    }
  }, [open, services, instruments]);

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
              <Label htmlFor="txn">Service</Label>
              <Select
                value={form.transaction_type}
                onValueChange={(v) => update("transaction_type", v)}
                disabled={services.length === 0}
              >
                <SelectTrigger id="txn">
                  <SelectValue placeholder="Choose a service…" />
                </SelectTrigger>
                <SelectContent>
                  {services.map((s) => (
                    <SelectItem key={s.id} value={s.code}>
                      {s.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {services.length === 0 && (
                <p className="mt-1 text-[11px] text-[--color-text-3]">
                  No active services — create one in /services first.
                </p>
              )}
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
              <Select
                value={form.currency}
                onValueChange={(v) => update("currency", v)}
                disabled={instruments.length === 0}
              >
                <SelectTrigger id="ccy">
                  <SelectValue placeholder="Choose…" />
                </SelectTrigger>
                <SelectContent>
                  {instruments.map((i) => (
                    <SelectItem key={i.id} value={i.code}>
                      {i.code} · {i.symbol}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
