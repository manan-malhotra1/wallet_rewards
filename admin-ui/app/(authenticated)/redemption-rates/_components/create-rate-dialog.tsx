/**
 * Create-conversion-rate dialog — a rate is keyed per (tenant, currency):
 * "`points_per_unit` PTS = `value_per_unit` currency", plus the optional
 * per-transaction anti-drain caps (absolute points and/or % of the user's
 * current balance, Pay-PRD-1295). PROPOSES a create through the maker-checker
 * pipeline (config_type "conversion_rate").
 *
 * With a `reviseRequest`, it opens in revise mode (pre-filled from the
 * proposal; revises + resubmits). With an `editRate` (a live row), it opens in
 * EDIT mode: the currency scope locks, and submitting PROPOSES an `update`.
 */
"use client";

import * as React from "react";

import { reviseAndResubmitConfigRequestAction } from "@/app/(authenticated)/config-requests/_actions";
import {
  proposeConversionRateChangeAction,
  proposeConversionRateUpdateAction,
} from "@/app/(authenticated)/redemption-rates/_actions";
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
import type { ConfigChangeRequest, PointsConversionRate } from "@/lib/api-types";

interface FormState {
  currency: string;
  points_per_unit: string;
  value_per_unit: string;
  max_points_per_txn: string;
  max_balance_pct_per_txn: string;
}

function str(value: unknown, fallback = ""): string {
  return value === null || value === undefined ? fallback : String(value);
}

/** Derive the initial form from a revise proposal, an edited live rate, or defaults. */
function initialForm(
  fiatCurrency: string,
  reviseRequest?: ConfigChangeRequest,
  editRate?: PointsConversionRate,
  options: string[] = [],
): FormState {
  const source = reviseRequest
    ? reviseRequest.payload
    : ((editRate as unknown as Record<string, unknown> | undefined) ?? null);
  if (source) {
    return {
      currency: str(source.currency, fiatCurrency),
      points_per_unit: str(source.points_per_unit, "100"),
      value_per_unit: str(source.value_per_unit, "10"),
      max_points_per_txn: str(source.max_points_per_txn),
      max_balance_pct_per_txn: str(source.max_balance_pct_per_txn),
    };
  }
  // Prefer the tenant's base currency when it's still un-configured, else the
  // first remaining option (so the dropdown never opens on a taken currency).
  const seed = options.includes(fiatCurrency) ? fiatCurrency : (options[0] ?? fiatCurrency);
  return {
    currency: seed,
    points_per_unit: "100",
    value_per_unit: "10",
    max_points_per_txn: "",
    max_balance_pct_per_txn: "",
  };
}

/** Human preview of the entered rate ("100 PTS = 10.00 ZAR"). */
function ratePreview(form: FormState): string | null {
  const pts = Number(form.points_per_unit);
  const val = Number(form.value_per_unit);
  if (!Number.isFinite(pts) || pts <= 0 || !Number.isFinite(val) || val <= 0) return null;
  return `${pts} PTS = ${val.toFixed(2)} ${form.currency.toUpperCase() || "?"}`;
}

export function CreateRateDialog({
  tenantId,
  defaultCurrency = "ZAR",
  currencies = [],
  configuredCurrencies = [],
  trigger,
  reviseRequest,
  editRate,
  open: controlledOpen,
  onOpenChange,
}: {
  tenantId: string;
  /** The active tenant's base currency — the create path's default. */
  defaultCurrency?: string;
  /**
   * The tenant's FINANCIAL currencies (from its active instruments) — the
   * dropdown's options. A rate can only target a currency the tenant actually
   * holds wallets in, so this is never free text.
   */
  currencies?: string[];
  /**
   * Currencies that already have a rate. On the create path they're filtered
   * out of the dropdown (one rate per currency; the backend 409s on a
   * duplicate). Ignored in edit/revise mode, where the scope is locked anyway.
   */
  configuredCurrencies?: string[];
  /** Trigger element; omit when driving the dialog via `open`/`onOpenChange`. */
  trigger?: React.ReactNode;
  reviseRequest?: ConfigChangeRequest;
  /** A live rate to edit in place (proposes an `update`; currency locks). */
  editRate?: PointsConversionRate;
  /** Controlled open state (edit affordance drives this); uncontrolled otherwise. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const editMode = Boolean(editRate);
  // The currency IS the scope: it locks when editing a live rate or revising a
  // sent-back UPDATE (both target an existing row's values, not its identity).
  const scopeLocked = editMode || reviseRequest?.operation === "update";
  // Create path: only currencies without a rate yet. Edit/revise: the locked
  // scope currency must stay selectable even though it's already configured.
  const options = React.useMemo(() => {
    const taken = new Set(configuredCurrencies.map((c) => c.toUpperCase()));
    const available = currencies.filter((c) => !taken.has(c.toUpperCase()));
    if (!scopeLocked) return available;
    const current = (editRate?.currency ?? "").toUpperCase();
    return current && !available.includes(current) ? [current, ...available] : available;
  }, [currencies, configuredCurrencies, scopeLocked, editRate]);

  const [form, setForm] = React.useState<FormState>(() =>
    initialForm(defaultCurrency, reviseRequest, editRate, options),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(defaultCurrency, reviseRequest, editRate, options));
      setErrorBanner(null);
    }
  }, [open, defaultCurrency, reviseRequest, editRate, options]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setErrorBanner(null);
    if (!form.currency) {
      setErrorBanner("Pick a currency. Add a financial instrument first if none are listed.");
      return;
    }
    const pts = Number(form.points_per_unit);
    const val = Number(form.value_per_unit);
    if (!Number.isFinite(pts) || pts <= 0 || !Number.isFinite(val) || val <= 0) {
      setErrorBanner("Both sides of the rate must be positive numbers.");
      return;
    }
    const pct = form.max_balance_pct_per_txn.trim();
    if (pct && (!Number.isFinite(Number(pct)) || Number(pct) <= 0 || Number(pct) > 100)) {
      setErrorBanner("The % of balance cap must be between 0 and 100.");
      return;
    }
    const capAbs = form.max_points_per_txn.trim();
    if (capAbs && (!Number.isFinite(Number(capAbs)) || Number(capAbs) <= 0)) {
      setErrorBanner("The per-transaction points cap must be a positive number.");
      return;
    }
    const payload = {
      tenant_id: tenantId,
      currency: form.currency.toUpperCase(),
      points_per_unit: form.points_per_unit,
      value_per_unit: form.value_per_unit,
      // Empty inputs mean "uncapped" — the backend expresses that as omitted.
      ...(capAbs ? { max_points_per_txn: capAbs } : {}),
      ...(pct ? { max_balance_pct_per_txn: pct } : {}),
    };
    setSubmitting(true);
    const result = reviseRequest
      ? await reviseAndResubmitConfigRequestAction(tenantId, reviseRequest.id, payload)
      : editRate
        ? await proposeConversionRateUpdateAction(tenantId, editRate.id, payload)
        : await proposeConversionRateChangeAction(payload);
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: reviseRequest
        ? "Resubmitted for approval"
        : "Change proposed — pending approval",
      description: ratePreview(form) ?? form.currency.toUpperCase(),
    });
    setOpen(false);
  };

  const preview = ratePreview(form);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {reviseRequest
              ? "Revise conversion rate"
              : editMode
                ? "Edit conversion rate"
                : "New conversion rate"}
          </DialogTitle>
          <DialogDescription>
            How many points convert into wallet money for this currency. Without
            a rate, internal redemption into the currency is blocked (fail-closed).
            Goes live after a second admin approves.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="rate-currency">Currency</Label>
              <Select
                value={form.currency}
                onValueChange={(v) => update("currency", v)}
                disabled={scopeLocked || options.length === 0}
              >
                <SelectTrigger id="rate-currency" className="mt-1">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {options.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="rate-points">Points</Label>
              <Input
                id="rate-points"
                type="number"
                min="0"
                value={form.points_per_unit}
                onChange={(e) => update("points_per_unit", e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="rate-value">= Value</Label>
              <Input
                id="rate-value"
                type="number"
                step="0.01"
                min="0"
                value={form.value_per_unit}
                onChange={(e) => update("value_per_unit", e.target.value)}
                className="mt-1"
              />
            </div>
          </div>
          {preview && (
            <p className="text-xs text-muted-foreground">
              Rate: <span className="font-mono">{preview}</span>
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="rate-cap-abs">Max points per txn</Label>
              <Input
                id="rate-cap-abs"
                type="number"
                min="0"
                placeholder="Uncapped"
                value={form.max_points_per_txn}
                onChange={(e) => update("max_points_per_txn", e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="rate-cap-pct">Max % of balance per txn</Label>
              <Input
                id="rate-cap-pct"
                type="number"
                step="0.01"
                min="0"
                max="100"
                placeholder="Uncapped"
                value={form.max_balance_pct_per_txn}
                onChange={(e) => update("max_balance_pct_per_txn", e.target.value)}
                className="mt-1"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Anti-drain caps: a single redemption may burn at most this many
            points and/or this share of the user&apos;s current balance (balance
            100 + 10% → at most 10 points at a time). Leave blank for no cap.
          </p>
          {errorBanner && (
            <ErrorBanner title="Couldn't propose" description={errorBanner} />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting
              ? reviseRequest
                ? "Resubmitting…"
                : "Proposing…"
              : reviseRequest
                ? "Resubmit"
                : "Propose change"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
