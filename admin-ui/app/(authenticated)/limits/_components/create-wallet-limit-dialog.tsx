/**
 * <CreateWalletLimitDialog> — admin form to PROPOSE a wallet-level limit.
 *
 * One config per (tenant, currency). Max balance + cumulative send/receive
 * count/value caps over daily/weekly/monthly windows. At least one must be set
 * (validated server-side too). Writes go through the maker-checker pipeline.
 *
 * With a `reviseRequest`, it opens in revise mode: pre-filled from the proposal,
 * the submit button reads "Resubmit", and it revises + resubmits the request
 * instead of proposing a new one.
 */
"use client";

import * as React from "react";

import { reviseAndResubmitConfigRequestAction } from "@/app/(authenticated)/config-requests/_actions";
import { proposeWalletLimitCreateAction } from "@/app/(authenticated)/limits/_actions";
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
import type { CreateWalletLimitConfigPayload } from "@/lib/api-endpoints";
import type { ConfigChangeRequest, Instrument, UserType } from "@/lib/api-types";

// [payload key, label, isCount] — drives both the inputs and the payload build.
type CapKey = keyof Omit<
  CreateWalletLimitConfigPayload,
  "tenant_id" | "currency" | "user_type"
>;
const CAP_FIELDS: [CapKey, string, boolean][] = [
  ["send_daily_count_cap", "Send · daily count", true],
  ["send_daily_value_cap", "Send · daily value", false],
  ["send_weekly_count_cap", "Send · weekly count", true],
  ["send_weekly_value_cap", "Send · weekly value", false],
  ["send_monthly_count_cap", "Send · monthly count", true],
  ["send_monthly_value_cap", "Send · monthly value", false],
  ["receive_daily_count_cap", "Receive · daily count", true],
  ["receive_daily_value_cap", "Receive · daily value", false],
  ["receive_weekly_count_cap", "Receive · weekly count", true],
  ["receive_weekly_value_cap", "Receive · weekly value", false],
  ["receive_monthly_count_cap", "Receive · monthly count", true],
  ["receive_monthly_value_cap", "Receive · monthly value", false],
];

type FormState = Record<"currency" | "max_balance" | "user_type" | CapKey, string>;

function str(value: unknown, fallback = ""): string {
  return value === null || value === undefined ? fallback : String(value);
}

/** Derive the initial form from a revise proposal, or fresh defaults. */
function initialForm(
  instruments: Instrument[],
  reviseRequest?: ConfigChangeRequest,
): FormState {
  const p = reviseRequest?.payload ?? null;
  const base = {
    currency: p ? str(p.currency) : (instruments[0]?.code ?? ""),
    max_balance: str(p?.max_balance),
    user_type: p?.user_type ? str(p.user_type) : "all",
  } as FormState;
  for (const [key] of CAP_FIELDS) base[key] = str(p?.[key]);
  return base;
}

export function CreateWalletLimitDialog({
  tenantId,
  instruments,
  trigger,
  reviseRequest,
}: {
  tenantId: string;
  instruments: Instrument[];
  trigger: React.ReactNode;
  reviseRequest?: ConfigChangeRequest;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() =>
    initialForm(instruments, reviseRequest),
  );
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(instruments, reviseRequest));
      setErrorBanner(null);
    }
  }, [open, instruments, reviseRequest]);

  const update = (key: keyof FormState, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setErrorBanner(null);
    const capValues = [form.max_balance, ...CAP_FIELDS.map(([k]) => form[k])];
    if (!capValues.some((v) => v.trim() !== "")) {
      setErrorBanner("Set a max balance or at least one cap.");
      return;
    }
    setSubmitting(true);
    const payload: CreateWalletLimitConfigPayload = {
      tenant_id: tenantId,
      currency: form.currency.toUpperCase(),
      user_type: form.user_type === "all" ? null : (form.user_type as UserType),
      max_balance: form.max_balance.trim() || undefined,
    };
    for (const [key, , isCount] of CAP_FIELDS) {
      const raw = form[key].trim();
      if (raw) {
        // Count caps are integers; value caps stay decimal strings.
        (payload[key] as number | string) = isCount ? Number(raw) : raw;
      }
    }
    const result = reviseRequest
      ? await reviseAndResubmitConfigRequestAction(
          tenantId,
          reviseRequest.id,
          { ...payload },
        )
      : await proposeWalletLimitCreateAction(tenantId, payload);
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: reviseRequest
        ? "Resubmitted for approval"
        : "Change proposed — pending approval",
      description: form.currency.toUpperCase(),
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {reviseRequest ? "Revise wallet limit" : "New wallet limit"}
          </DialogTitle>
          <DialogDescription>
            Per-(tenant, currency) ceiling on a user&apos;s financial wallet. Set a
            max balance and/or cumulative send/receive caps.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="wlc-ccy">Currency</Label>
              <Select
                value={form.currency}
                onValueChange={(v) => update("currency", v)}
                disabled={instruments.length === 0}
              >
                <SelectTrigger id="wlc-ccy">
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
              <Label htmlFor="wlc-max">Max balance</Label>
              <Input
                id="wlc-max"
                value={form.max_balance}
                onChange={(e) => update("max_balance", e.target.value)}
                placeholder="50000"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="wlc-utype">User type</Label>
              <Select
                value={form.user_type}
                onValueChange={(v) => update("user_type", v)}
              >
                <SelectTrigger id="wlc-utype">
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
            {CAP_FIELDS.map(([key, label, isCount]) => (
              <div key={key}>
                <Label htmlFor={`wlc-${key}`}>{label}</Label>
                <Input
                  id={`wlc-${key}`}
                  type={isCount ? "number" : "text"}
                  value={form[key]}
                  onChange={(e) => update(key, e.target.value)}
                  placeholder={isCount ? "10" : "25000"}
                />
              </div>
            ))}
          </div>
          {errorBanner && <ErrorBanner title="Validation" description={errorBanner} />}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={submitting}>
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
