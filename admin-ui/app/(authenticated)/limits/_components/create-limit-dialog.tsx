/**
 * <CreateLimitDialog> — admin form for POST /limits/configs.
 *
 * Min and max are optional; at least one of (min, max, daily_count_cap,
 * daily_value_cap) must be set (validated server-side).
 */
"use client";

import * as React from "react";

import { createLimitConfigAction } from "@/app/(authenticated)/limits/_actions";
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
  min_amount: string;
  max_amount: string;
  daily_count_cap: string;
  daily_value_cap: string;
}

const INITIAL: FormState = {
  transaction_type: "p2p",
  account_type: "financial_wallet",
  currency: "ZAR",
  min_amount: "",
  max_amount: "",
  daily_count_cap: "",
  daily_value_cap: "",
};

export function CreateLimitDialog({
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
    if (
      !form.min_amount &&
      !form.max_amount &&
      !form.daily_count_cap &&
      !form.daily_value_cap
    ) {
      setErrorBanner("Set at least one of min, max, daily count, daily value.");
      return;
    }
    setSubmitting(true);
    const result = await createLimitConfigAction({
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      account_type: form.account_type,
      currency: form.currency.toUpperCase(),
      min_amount: form.min_amount || undefined,
      max_amount: form.max_amount || undefined,
      daily_count_cap: form.daily_count_cap
        ? Number(form.daily_count_cap)
        : undefined,
      daily_value_cap: form.daily_value_cap || undefined,
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
            At least one of min, max, daily count, or daily value must be set.
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
                placeholder="ZAR"
                maxLength={3}
              />
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
