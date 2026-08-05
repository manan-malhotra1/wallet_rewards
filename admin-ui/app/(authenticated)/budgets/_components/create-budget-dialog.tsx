/**
 * <CreateBudgetDialog> — the admin "New reward budget" form.
 *
 * Currency is picked from the tenant's instrument catalog (PTS + every
 * financial currency), never free-typed. A tenant-wide budget in a
 * multi-currency tenant is special: caps are per currency, and one click
 * creates one budget per currency that has a cap filled in (blank rows
 * are skipped). Rule-scoped budgets — and single-currency tenants —
 * stay a single currency + single cap.
 */
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

type WindowType = "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";

interface FormState {
  scope_type: "tenant" | "rule";
  scope_id: string;
  /** Single-currency mode: the chosen currency. */
  currency: string;
  window_type: WindowType;
  /** Single-currency mode: the one cap. */
  cap_amount: string;
  /** Multi-currency mode: currency code → cap string (blank = skip). */
  caps: Record<string, string>;
}

export function CreateBudgetDialog({
  tenantId,
  currencies,
  trigger,
}: {
  tenantId: string;
  currencies: string[];
  trigger: React.ReactNode;
}) {
  const initial: FormState = React.useMemo(
    () => ({
      scope_type: "tenant",
      scope_id: "",
      currency: currencies[0] ?? "PTS",
      window_type: "lifetime",
      cap_amount: "10000",
      caps: {},
    }),
    [currencies],
  );

  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(initial);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initial);
      setErrorBanner(null);
    }
  }, [open, initial]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // Per-currency caps only apply to a tenant-wide budget in a tenant with
  // more than one currency. Rule scope and single-currency tenants keep the
  // single dropdown + single cap.
  const multiCurrency = form.scope_type === "tenant" && currencies.length > 1;

  const onSubmit = async () => {
    setErrorBanner(null);
    if (form.scope_type === "rule" && !form.scope_id) {
      setErrorBanner("Rule scope requires a rule_id.");
      return;
    }

    if (multiCurrency) {
      const entries = currencies
        .map((code) => ({ code, cap: (form.caps[code] ?? "").trim() }))
        .filter((e) => e.cap !== "");
      if (entries.length === 0) {
        setErrorBanner("Enter a cap for at least one currency.");
        return;
      }
      if (entries.some((e) => !(parseFloat(e.cap) > 0))) {
        setErrorBanner("Every entered cap must be a positive number.");
        return;
      }
      setSubmitting(true);
      const results = await Promise.all(
        entries.map((e) =>
          createBudgetAction({
            tenant_id: tenantId,
            scope_type: "tenant",
            scope_id: undefined,
            currency: e.code.toUpperCase(),
            window_type: form.window_type,
            cap_amount: e.cap,
          }),
        ),
      );
      setSubmitting(false);
      const failed = results.find((r) => !r.ok);
      if (failed && !failed.ok) {
        setErrorBanner(`${failed.errorCode}: ${failed.message}`);
        return;
      }
      toast({
        title:
          entries.length === 1
            ? "Budget created"
            : `${entries.length} budgets created`,
        description: `tenant · ${form.window_type}`,
      });
      setOpen(false);
      return;
    }

    // Single-currency mode.
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
                onValueChange={(v) => update("window_type", v as WindowType)}
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

          {multiCurrency ? (
            <div>
              <Label>Caps by currency</Label>
              <p className="mt-1 text-[10px] text-muted-foreground">
                Enter a cap for each currency you want to budget. Blank rows
                are skipped — one budget is created per filled-in currency.
              </p>
              <div className="mt-2 space-y-2">
                {currencies.map((code) => (
                  <div key={code} className="grid grid-cols-[4rem_1fr] items-center gap-3">
                    <span className="text-sm font-medium">{code}</span>
                    <Input
                      aria-label={`Cap for ${code}`}
                      value={form.caps[code] ?? ""}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          caps: { ...prev.caps, [code]: e.target.value },
                        }))
                      }
                      placeholder="Cap amount (blank = skip)"
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="ccy">Currency</Label>
                <Select
                  value={form.currency}
                  onValueChange={(v) => update("currency", v)}
                >
                  <SelectTrigger id="ccy">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {currencies.map((code) => (
                      <SelectItem key={code} value={code}>
                        {code}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
          )}
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
