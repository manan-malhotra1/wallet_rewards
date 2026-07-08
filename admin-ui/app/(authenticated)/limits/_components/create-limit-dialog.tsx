/**
 * <CreateLimitDialog> — admin form for POST /limits/configs.
 *
 * Min and max are optional; at least one of (min, max, daily_count_cap,
 * daily_value_cap) must be set (validated server-side).
 */
"use client";

import * as React from "react";

import { createLimitConfigAction } from "@/app/(authenticated)/limits/_actions";
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
  account_type: string;
  currency: string;
  user_type: string;
  min_amount: string;
  max_amount: string;
  daily_count_cap: string;
  daily_value_cap: string;
  weekly_count_cap: string;
  weekly_value_cap: string;
  monthly_count_cap: string;
  monthly_value_cap: string;
}

function initialForm(services: Service[], instruments: Instrument[]): FormState {
  return {
    transaction_type: services[0]?.code ?? "",
    account_type: "financial_wallet",
    currency:
      instruments.find((i) => i.account_type === "financial_wallet")?.code ??
      instruments[0]?.code ??
      "",
    user_type: "all",
    min_amount: "",
    max_amount: "",
    daily_count_cap: "",
    daily_value_cap: "",
    weekly_count_cap: "",
    weekly_value_cap: "",
    monthly_count_cap: "",
    monthly_value_cap: "",
  };
}

export function CreateLimitDialog({
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
    const anyCap = [
      form.min_amount,
      form.max_amount,
      form.daily_count_cap,
      form.daily_value_cap,
      form.weekly_count_cap,
      form.weekly_value_cap,
      form.monthly_count_cap,
      form.monthly_value_cap,
    ].some((v) => v.trim() !== "");
    if (!anyCap) {
      setErrorBanner("Set at least one cap.");
      return;
    }
    setSubmitting(true);
    const num = (v: string) => (v.trim() ? Number(v) : undefined);
    const str = (v: string) => (v.trim() ? v : undefined);
    const result = await createLimitConfigAction({
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      account_type: form.account_type,
      currency: form.currency.toUpperCase(),
      user_type: form.user_type === "all" ? null : (form.user_type as UserType),
      min_amount: str(form.min_amount),
      max_amount: str(form.max_amount),
      daily_count_cap: num(form.daily_count_cap),
      daily_value_cap: str(form.daily_value_cap),
      weekly_count_cap: num(form.weekly_count_cap),
      weekly_value_cap: str(form.weekly_value_cap),
      monthly_count_cap: num(form.monthly_count_cap),
      monthly_value_cap: str(form.monthly_value_cap),
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Limit created",
      description: `${form.transaction_type} · ${form.currency}`,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New limit</DialogTitle>
          <DialogDescription>
            Per-txn min/max plus rolling daily/weekly/monthly caps. At least one
            must be set.
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
              <Label htmlFor="utype">User type</Label>
              <Select
                value={form.user_type}
                onValueChange={(v) => update("user_type", v)}
              >
                <SelectTrigger id="utype">
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
              <Label htmlFor="min">Min amount</Label>
              <Input
                id="min"
                value={form.min_amount}
                onChange={(e) => update("min_amount", e.target.value)}
                placeholder="50"
              />
            </div>
            <div>
              <Label htmlFor="max">Max amount</Label>
              <Input
                id="max"
                value={form.max_amount}
                onChange={(e) => update("max_amount", e.target.value)}
                placeholder="5000"
              />
            </div>
            <div>
              <Label htmlFor="dc">Daily count cap</Label>
              <Input
                id="dc"
                type="number"
                value={form.daily_count_cap}
                onChange={(e) => update("daily_count_cap", e.target.value)}
                placeholder="10"
              />
            </div>
            <div>
              <Label htmlFor="dv">Daily value cap</Label>
              <Input
                id="dv"
                value={form.daily_value_cap}
                onChange={(e) => update("daily_value_cap", e.target.value)}
                placeholder="25000"
              />
            </div>
            <div>
              <Label htmlFor="wc">Weekly count cap</Label>
              <Input
                id="wc"
                type="number"
                value={form.weekly_count_cap}
                onChange={(e) => update("weekly_count_cap", e.target.value)}
                placeholder="50"
              />
            </div>
            <div>
              <Label htmlFor="wv">Weekly value cap</Label>
              <Input
                id="wv"
                value={form.weekly_value_cap}
                onChange={(e) => update("weekly_value_cap", e.target.value)}
                placeholder="100000"
              />
            </div>
            <div>
              <Label htmlFor="mc">Monthly count cap</Label>
              <Input
                id="mc"
                type="number"
                value={form.monthly_count_cap}
                onChange={(e) => update("monthly_count_cap", e.target.value)}
                placeholder="200"
              />
            </div>
            <div>
              <Label htmlFor="mv">Monthly value cap</Label>
              <Input
                id="mv"
                value={form.monthly_value_cap}
                onChange={(e) => update("monthly_value_cap", e.target.value)}
                placeholder="400000"
              />
            </div>
          </div>
          {errorBanner && <ErrorBanner title="Validation" description={errorBanner} />}
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
