/**
 * Create-step-up dialog — a step-up PIN policy is keyed per (tenant,
 * transaction_type, currency): transactions above `threshold_amount` require
 * the user to re-enter their PIN. PROPOSES a create through the maker-checker
 * pipeline (config_type "step_up").
 *
 * With a `reviseRequest`, it opens in revise mode (pre-filled from the proposal;
 * revises + resubmits). With an `editPolicy` (a live policy row), it opens in
 * EDIT mode: pre-filled with the scope fields locked, and submitting PROPOSES an
 * `update` against the row's id.
 */
"use client";

import * as React from "react";

import { reviseAndResubmitConfigRequestAction } from "@/app/(authenticated)/config-requests/_actions";
import {
  proposeStepUpChangeAction,
  proposeStepUpUpdateAction,
} from "@/app/(authenticated)/step-up/_actions";
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
import type { ConfigChangeRequest, StepUpPolicy } from "@/lib/api-types";

// The user-initiated transaction types enforce_step_up guards (mirrors the
// backend step_up TransactionType Literal). A step-up policy can exist for any
// of these, so the dialog must represent all of them — collapsing to p2p breaks
// editing a cashout/cash_in/airtime policy (its scope would no longer match).
type TxnType = "p2p" | "redemption" | "cashout" | "cash_in" | "airtime_recharge";

const TXN_TYPE_LABELS: Record<TxnType, string> = {
  p2p: "Peer-to-peer (money)",
  redemption: "Redemption (points)",
  cashout: "Cash-out (money)",
  cash_in: "Cash-in (money)",
  airtime_recharge: "Airtime recharge (money)",
};

const TXN_TYPES = Object.keys(TXN_TYPE_LABELS) as TxnType[];

/**
 * Redemption settles in points; every other guarded type is fiat, defaulting
 * to the active tenant's own currency (never a hardcoded "ZAR").
 */
function defaultCurrencyFor(txn: TxnType, fiatCurrency: string): string {
  return txn === "redemption" ? "PTS" : fiatCurrency;
}

/** Coerce an arbitrary stored value to a known TxnType (default p2p if unknown). */
function toTxnType(value: unknown): TxnType {
  return TXN_TYPES.includes(value as TxnType) ? (value as TxnType) : "p2p";
}

interface FormState {
  transaction_type: TxnType;
  currency: string;
  threshold_amount: string;
}

function str(value: unknown, fallback = ""): string {
  return value === null || value === undefined ? fallback : String(value);
}

/** Derive the initial form from a revise proposal, an edited live policy, or defaults. */
function initialForm(
  fiatCurrency: string,
  reviseRequest?: ConfigChangeRequest,
  editPolicy?: StepUpPolicy,
): FormState {
  // Revise takes precedence over edit.
  const source = reviseRequest
    ? reviseRequest.payload
    : ((editPolicy as unknown as Record<string, unknown> | undefined) ?? null);
  if (source) {
    // Preserve the policy's ACTUAL transaction_type — do NOT collapse it, or an
    // edit of a cashout/cash_in/airtime policy would submit p2p and scope-mismatch.
    return {
      transaction_type: toTxnType(source.transaction_type),
      currency: str(source.currency, fiatCurrency),
      threshold_amount: str(source.threshold_amount, "0"),
    };
  }
  // A fresh create: p2p seeded with the tenant's fiat currency.
  return {
    transaction_type: "p2p",
    currency: fiatCurrency,
    threshold_amount: "200",
  };
}

export function CreateStepUpDialog({
  tenantId,
  defaultCurrency = "ZAR",
  trigger,
  reviseRequest,
  editPolicy,
  open: controlledOpen,
  onOpenChange,
}: {
  tenantId: string;
  /**
   * The active tenant's base currency — the create path's fiat default. Only
   * used when creating a fresh policy; edit/revise take the currency from the
   * source policy, so it falls back to "ZAR" where unthreaded.
   */
  defaultCurrency?: string;
  /** Trigger element; omit when driving the dialog via `open`/`onOpenChange`. */
  trigger?: React.ReactNode;
  reviseRequest?: ConfigChangeRequest;
  /** A live step-up policy to edit in place (proposes an `update`). */
  editPolicy?: StepUpPolicy;
  /** Controlled open state (edit affordance drives this); uncontrolled otherwise. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const editMode = Boolean(editPolicy);
  // Scope (transaction_type + currency) locks when editing a live policy OR
  // revising a sent-back UPDATE — both target an existing policy's values, not
  // its identity. A create revise keeps scope editable.
  const scopeLocked = editMode || reviseRequest?.operation === "update";
  const [form, setForm] = React.useState<FormState>(() =>
    initialForm(defaultCurrency, reviseRequest, editPolicy),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(defaultCurrency, reviseRequest, editPolicy));
      setErrorBanner(null);
    }
  }, [open, defaultCurrency, reviseRequest, editPolicy]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // Currency defaults sensibly per txn type — redemption is points, every other
  // guarded type is fiat. Only auto-correct while the scope is editable (a
  // locked scope is fixed).
  React.useEffect(() => {
    if (scopeLocked) return;
    const expected = defaultCurrencyFor(form.transaction_type, defaultCurrency);
    if (form.currency !== expected) {
      update("currency", expected);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.transaction_type, scopeLocked, defaultCurrency]);

  const onSubmit = async () => {
    setErrorBanner(null);
    const n = Number(form.threshold_amount);
    if (!Number.isFinite(n) || n < 0) {
      setErrorBanner("Threshold must be a non-negative number.");
      return;
    }
    const payload = {
      tenant_id: tenantId,
      transaction_type: form.transaction_type,
      currency: form.currency.toUpperCase(),
      threshold_amount: form.threshold_amount,
    };
    setSubmitting(true);
    const result = reviseRequest
      ? await reviseAndResubmitConfigRequestAction(
          tenantId,
          reviseRequest.id,
          payload,
        )
      : editPolicy
        ? await proposeStepUpUpdateAction(tenantId, editPolicy.id, payload)
        : await proposeStepUpChangeAction(payload);
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: reviseRequest
        ? "Resubmitted for approval"
        : "Change proposed — pending approval",
      description: `${form.transaction_type} · ${form.currency.toUpperCase()}`,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {reviseRequest
              ? "Revise step-up policy"
              : editMode
                ? "Edit step-up policy"
                : "New step-up policy"}
          </DialogTitle>
          <DialogDescription>
            Transactions exceeding the threshold below will require the user to
            re-enter their PIN. Goes live after a second admin approves.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label>Transaction type</Label>
            <Select
              value={form.transaction_type}
              onValueChange={(v) => update("transaction_type", v as TxnType)}
              disabled={scopeLocked}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TXN_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {TXN_TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="currency">Currency</Label>
              <Input
                id="currency"
                value={form.currency}
                onChange={(e) => update("currency", e.target.value)}
                maxLength={3}
                disabled={scopeLocked}
                className="mt-1 uppercase"
              />
            </div>
            <div>
              <Label htmlFor="threshold">Threshold</Label>
              <Input
                id="threshold"
                type="number"
                step="0.01"
                min="0"
                value={form.threshold_amount}
                onChange={(e) => update("threshold_amount", e.target.value)}
                className="mt-1"
              />
            </div>
          </div>
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
