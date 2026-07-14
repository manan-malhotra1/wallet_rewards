/**
 * Create-tax dialog (Epic 24 / Story 24.2). Tax is keyed per (tenant,
 * currency) with independent fee/commission rates + inclusive flags. PROPOSES
 * a create through the maker-checker pipeline.
 */
"use client";

import * as React from "react";

import { proposeTaxChangeAction } from "@/app/(authenticated)/taxes/_actions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import type { Instrument } from "@/lib/api-types";

interface FormState {
  currency: string;
  fee_tax_pct: string;
  commission_tax_pct: string;
  fee_tax_inclusive: boolean;
  commission_tax_inclusive: boolean;
}

function initialForm(instruments: Instrument[]): FormState {
  return {
    currency:
      instruments.find((i) => i.account_type === "financial_wallet")?.code ??
      instruments[0]?.code ??
      "",
    fee_tax_pct: "0",
    commission_tax_pct: "0",
    fee_tax_inclusive: false,
    commission_tax_inclusive: false,
  };
}

export function CreateTaxDialog({
  tenantId,
  instruments,
  trigger,
}: {
  tenantId: string;
  instruments: Instrument[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() =>
    initialForm(instruments),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(instruments));
      setErrorBanner(null);
    }
  }, [open, instruments]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setErrorBanner(null);
    setSubmitting(true);
    const result = await proposeTaxChangeAction({
      tenant_id: tenantId,
      currency: form.currency.toUpperCase(),
      fee_tax_pct: form.fee_tax_pct || "0",
      commission_tax_pct: form.commission_tax_pct || "0",
      fee_tax_inclusive: form.fee_tax_inclusive,
      commission_tax_inclusive: form.commission_tax_inclusive,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Change proposed — pending approval",
      description: `Tax · ${form.currency}`,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New tax config</DialogTitle>
          <DialogDescription>
            One tax config per currency — applied to fees and commissions
            independently. Goes live after a second admin approves.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="t-ccy">Currency</Label>
            <Select
              value={form.currency}
              onValueChange={(v) => update("currency", v)}
              disabled={instruments.length === 0}
            >
              <SelectTrigger id="t-ccy">
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
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="t-fee">Fee tax %</Label>
              <Input
                id="t-fee"
                value={form.fee_tax_pct}
                onChange={(e) => update("fee_tax_pct", e.target.value)}
                placeholder="0.15"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                As a decimal: 0.15 = 15%
              </p>
            </div>
            <div>
              <Label htmlFor="t-comm">Commission tax %</Label>
              <Input
                id="t-comm"
                value={form.commission_tax_pct}
                onChange={(e) => update("commission_tax_pct", e.target.value)}
                placeholder="0.15"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                As a decimal: 0.15 = 15%
              </p>
            </div>
          </div>
          <div className="space-y-2">
            <Checkbox
              checked={form.fee_tax_inclusive}
              onChange={(e) => update("fee_tax_inclusive", e.target.checked)}
              label="Fee tax inclusive (tax carved out of the fee, not added on top)"
            />
            <Checkbox
              checked={form.commission_tax_inclusive}
              onChange={(e) =>
                update("commission_tax_inclusive", e.target.checked)
              }
              label="Commission tax inclusive (tax carved out of the commission)"
            />
          </div>
          {errorBanner && (
            <ErrorBanner title="Couldn't propose" description={errorBanner} />
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Proposing…" : "Propose change"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
