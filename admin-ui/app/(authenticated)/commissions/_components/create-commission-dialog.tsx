/**
 * Create-commission dialog (Epic 24 / Story 24.2). Collects a commission
 * config incl. an optional slab band, then PROPOSES a create through the
 * maker-checker pipeline. Nothing goes live until a second admin approves.
 */
"use client";

import * as React from "react";

import { proposeCommissionChangeAction } from "@/app/(authenticated)/commissions/_actions";
import { USER_TYPE_OPTIONS } from "@/app/(authenticated)/users/_components/user-type-badge";
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
import type { Instrument, Service, UserType } from "@/lib/api-types";

interface FormState {
  transaction_type: string;
  currency: string;
  user_type: string;
  amount_from: string;
  amount_to: string;
  fixed_commission: string;
  variable_commission_pct: string;
  commission_cap: string;
}

function initialForm(services: Service[], instruments: Instrument[]): FormState {
  return {
    transaction_type: services[0]?.code ?? "",
    currency:
      instruments.find((i) => i.account_type === "financial_wallet")?.code ??
      instruments[0]?.code ??
      "",
    user_type: "all",
    amount_from: "",
    amount_to: "",
    fixed_commission: "0",
    variable_commission_pct: "0",
    commission_cap: "",
  };
}

export function CreateCommissionDialog({
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
    if (
      form.amount_from &&
      form.amount_to &&
      parseFloat(form.amount_to) <= parseFloat(form.amount_from)
    ) {
      setErrorBanner("Band upper bound must be greater than the lower bound.");
      return;
    }
    setSubmitting(true);
    const result = await proposeCommissionChangeAction({
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      currency: form.currency.toUpperCase(),
      user_type: form.user_type === "all" ? null : (form.user_type as UserType),
      amount_from: form.amount_from || undefined,
      amount_to: form.amount_to || undefined,
      fixed_commission: form.fixed_commission || "0",
      variable_commission_pct: form.variable_commission_pct || "0",
      commission_cap: form.commission_cap || undefined,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Change proposed — pending approval",
      description: `${form.transaction_type} · ${form.currency}`,
    });
    setOpen(false);
  };

  // Live payout preview — samples inside the band (midpoint when bounded).
  const { sampleAmount, preview } = React.useMemo(() => {
    const from = form.amount_from ? parseFloat(form.amount_from) : null;
    const to = form.amount_to ? parseFloat(form.amount_to) : null;
    let amount = 1000;
    if (from !== null && to !== null) amount = (from + to) / 2;
    else if (from !== null) amount = from;
    else if (to !== null) amount = to;
    const fixed = parseFloat(form.fixed_commission) || 0;
    const pct = parseFloat(form.variable_commission_pct) || 0;
    const cap = form.commission_cap ? parseFloat(form.commission_cap) : Infinity;
    const variable = Math.min(pct * amount, cap);
    return { sampleAmount: amount, preview: (fixed + variable).toFixed(2) };
  }, [
    form.fixed_commission,
    form.variable_commission_pct,
    form.commission_cap,
    form.amount_from,
    form.amount_to,
  ]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New commission config</DialogTitle>
          <DialogDescription>
            Commission = fixed + min(variable% × amount, cap). Changes are
            proposed and go live after a second admin approves.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="c-txn">Service</Label>
              <Select
                value={form.transaction_type}
                onValueChange={(v) => update("transaction_type", v)}
                disabled={services.length === 0}
              >
                <SelectTrigger id="c-txn">
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
                <p className="mt-1 text-[11px] text-muted-foreground">
                  No active services — create one in /services first.
                </p>
              )}
            </div>
            <div>
              <Label htmlFor="c-ccy">Currency</Label>
              <Select
                value={form.currency}
                onValueChange={(v) => update("currency", v)}
                disabled={instruments.length === 0}
              >
                <SelectTrigger id="c-ccy">
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
            <div>
              <Label htmlFor="c-utype">User type</Label>
              <Select
                value={form.user_type}
                onValueChange={(v) => update("user_type", v)}
              >
                <SelectTrigger id="c-utype">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All types (default)</SelectItem>
                  {USER_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="c-afrom">Band from (optional)</Label>
              <Input
                id="c-afrom"
                value={form.amount_from}
                onChange={(e) => update("amount_from", e.target.value)}
                placeholder="0"
              />
            </div>
            <div>
              <Label htmlFor="c-ato">Band to (optional)</Label>
              <Input
                id="c-ato"
                value={form.amount_to}
                onChange={(e) => update("amount_to", e.target.value)}
                placeholder="100"
              />
            </div>
          </div>
          <p className="-mt-2 text-[10px] text-muted-foreground">
            Leave the band empty to apply this commission to all amounts.
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="c-fixed">Fixed commission</Label>
              <Input
                id="c-fixed"
                value={form.fixed_commission}
                onChange={(e) => update("fixed_commission", e.target.value)}
                placeholder="2"
              />
            </div>
            <div>
              <Label htmlFor="c-varpct">Variable %</Label>
              <Input
                id="c-varpct"
                value={form.variable_commission_pct}
                onChange={(e) =>
                  update("variable_commission_pct", e.target.value)
                }
                placeholder="0.01"
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                As a decimal: 0.01 = 1%
              </p>
            </div>
            <div>
              <Label htmlFor="c-cap">Commission cap (optional)</Label>
              <Input
                id="c-cap"
                value={form.commission_cap}
                onChange={(e) => update("commission_cap", e.target.value)}
                placeholder="25"
              />
            </div>
          </div>
          <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
            On a sample{" "}
            <span className="font-mono text-foreground">
              {sampleAmount.toFixed(2)}
            </span>{" "}
            transaction, the commission would be{" "}
            <span className="font-mono text-foreground">{preview}</span>.
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
