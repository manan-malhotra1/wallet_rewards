"use client";

import * as React from "react";

import { createBudgetAction } from "@/app/(authenticated)/budgets/_actions";
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
  scope_type: "tenant" | "rule";
  scope_id: string;
  currency: string;
  window_type: "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";
  cap_amount: string;
}

const INITIAL: FormState = {
  scope_type: "tenant",
  scope_id: "",
  currency: "PTS",
  window_type: "lifetime",
  cap_amount: "10000",
};

export function CreateBudgetDialog({
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
    if (form.scope_type === "rule" && !form.scope_id) {
      setErrorBanner("Rule scope requires a rule_id.");
      return;
    }
    if (!form.cap_amount || parseFloat(form.cap_amount) <= 0) {
      setErrorBanner("Cap must be a positive number.");
      return;
    }
    setSubmitting(true);
    const result = await createBudgetAction({
      tenant_id: tenantId,
      scope_type: form.scope_type,
      scope_id: form.scope_type === "rule" ? form.scope_id : undefined,
      currency: form.currency.toUpperCase(),
      window_type: form.window_type,
      cap_amount: form.cap_amount,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Budget created",
      description: `${form.scope_type} · ${form.window_type}`,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New reward budget</DialogTitle>
          <DialogDescription>
            Caps how much can be issued within the chosen window. Threshold
            crossings (50% / 80% / 100%) write audit_log entries.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="scope">Scope</Label>
              <Select
                value={form.scope_type}
                onValueChange={(v) => update("scope_type", v as FormState["scope_type"])}
              >
                <SelectTrigger id="scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tenant">Tenant-wide</SelectItem>
                  <SelectItem value="rule">Specific rule</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="window">Window</Label>
              <Select
                value={form.window_type}
                onValueChange={(v) =>
                  update("window_type", v as FormState["window_type"])
                }
              >
                <SelectTrigger id="window">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="rolling_24h">Rolling 24h</SelectItem>
                  <SelectItem value="rolling_7d">Rolling 7d</SelectItem>
                  <SelectItem value="calendar_month">Calendar month</SelectItem>
                  <SelectItem value="lifetime">Lifetime</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {form.scope_type === "rule" && (
            <div>
              <Label htmlFor="rule-id">Rule ID</Label>
              <Input
                id="rule-id"
                value={form.scope_id}
                onChange={(e) => update("scope_id", e.target.value)}
                placeholder="UUID of the rule"
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="ccy">Currency</Label>
              <Input
                id="ccy"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={3}
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                PTS for points, ISO 4217 for cashback
              </p>
            </div>
            <div>
              <Label htmlFor="cap">Cap amount</Label>
              <Input
                id="cap"
                value={form.cap_amount}
                onChange={(e) => update("cap_amount", e.target.value)}
                placeholder="10000"
              />
            </div>
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
