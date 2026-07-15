/**
 * Create-commission dialog (Epic 24 / Story 24.2; Epic 25 / Task 8).
 *
 * Collects a commission SCHEDULE — shared scope (service / currency / user
 * type) plus a repeatable list of amount bands, each with its own fixed +
 * variable% + cap — then PROPOSES a create through the maker-checker pipeline.
 *
 * With a `reviseRequest`, it opens in revise mode: pre-filled from the
 * proposal, the submit button reads "Resubmit", and it revises + resubmits the
 * request instead of proposing a new one.
 *
 * With an `editConfig` (a live commission row), it opens in EDIT mode (Task 1):
 * pre-filled from that row with the scope fields locked, and submitting
 * PROPOSES an `update` against the row's id. Bands may still be added/removed.
 */
"use client";

import { Plus, Trash2 } from "lucide-react";
import * as React from "react";

import {
  proposeCommissionBandsAction,
  proposeCommissionUpdateAction,
} from "@/app/(authenticated)/commissions/_actions";
import { reviseAndResubmitConfigRequestAction } from "@/app/(authenticated)/config-requests/_actions";
import {
  emptyBand,
  orNull,
  validateBands,
  type BandRow,
} from "@/app/(authenticated)/_components/bands";
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
import type {
  CommissionConfig,
  ConfigChangeRequest,
  Instrument,
  Service,
  UserType,
} from "@/lib/api-types";

interface Scope {
  transaction_type: string;
  currency: string;
  user_type: string;
}

/** Extract the band rows from a proposal payload (multi-band or legacy flat). */
function bandsFromPayload(
  payload: Record<string, unknown> | null,
): Record<string, unknown>[] {
  if (!payload) return [];
  const bands = (payload as { bands?: unknown }).bands;
  return Array.isArray(bands)
    ? (bands as Record<string, unknown>[])
    : [payload];
}

function str(value: unknown, fallback = ""): string {
  return value === null || value === undefined ? fallback : String(value);
}

/** Derive the initial scope + bands, from a revise proposal, an edited live row, or fresh defaults. */
function deriveInitial(
  reviseRequest: ConfigChangeRequest | undefined,
  editConfig: CommissionConfig | undefined,
  services: Service[],
  instruments: Instrument[],
): { scope: Scope; bands: BandRow[] } {
  // Revise takes precedence over edit; a live row is a single-band source.
  const source = reviseRequest
    ? reviseRequest.payload
    : ((editConfig as Record<string, unknown> | undefined) ?? null);
  if (source) {
    const rows = bandsFromPayload(source);
    const first = rows[0] ?? {};
    return {
      scope: {
        transaction_type: str(first.transaction_type),
        currency: str(first.currency),
        user_type: first.user_type ? str(first.user_type) : "all",
      },
      bands: rows.map((r) => ({
        amount_from: str(r.amount_from),
        amount_to: str(r.amount_to),
        fixed: str(r.fixed_commission, "0"),
        variable_pct: str(r.variable_commission_pct, "0"),
        cap: str(r.commission_cap),
      })),
    };
  }
  return {
    scope: {
      transaction_type: services[0]?.code ?? "",
      currency:
        instruments.find((i) => i.account_type === "financial_wallet")?.code ??
        instruments[0]?.code ??
        "",
      user_type: "all",
    },
    bands: [emptyBand()],
  };
}

/** Live payout preview for one band — samples inside the band. */
function bandPreview(band: BandRow): { sample: number; commission: string } {
  const from = band.amount_from ? parseFloat(band.amount_from) : null;
  const to = band.amount_to ? parseFloat(band.amount_to) : null;
  let sample = 1000;
  if (from !== null && to !== null) sample = (from + to) / 2;
  else if (from !== null) sample = from;
  else if (to !== null) sample = to;
  const fixed = parseFloat(band.fixed) || 0;
  const pct = parseFloat(band.variable_pct) || 0;
  const cap = band.cap ? parseFloat(band.cap) : Infinity;
  const variable = Math.min(pct * sample, cap);
  return { sample, commission: (fixed + variable).toFixed(2) };
}

export function CreateCommissionDialog({
  tenantId,
  services,
  instruments,
  trigger,
  reviseRequest,
  editConfig,
  open: controlledOpen,
  onOpenChange,
}: {
  tenantId: string;
  services: Service[];
  instruments: Instrument[];
  /** Trigger element; omit when driving the dialog via `open`/`onOpenChange`. */
  trigger?: React.ReactNode;
  reviseRequest?: ConfigChangeRequest;
  /** A live commission row to edit in place (proposes an `update`). */
  editConfig?: CommissionConfig;
  /** Controlled open state (edit affordance drives this); uncontrolled otherwise. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const editMode = Boolean(editConfig);
  // Scope (identity) fields lock when editing a live config OR revising a
  // sent-back UPDATE — both target an existing config's values, not its
  // identity. A create revise keeps scope editable.
  const scopeLocked = editMode || reviseRequest?.operation === "update";
  const initial = React.useMemo(
    () => deriveInitial(reviseRequest, editConfig, services, instruments),
    [reviseRequest, editConfig, services, instruments],
  );
  const [scope, setScope] = React.useState<Scope>(initial.scope);
  const [bands, setBands] = React.useState<BandRow[]>(initial.bands);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setScope(initial.scope);
      setBands(initial.bands);
      setErrorBanner(null);
    }
  }, [open, initial]);

  const updateScope = <K extends keyof Scope>(key: K, value: Scope[K]) =>
    setScope((prev) => ({ ...prev, [key]: value }));

  const updateBand = (index: number, key: keyof BandRow, value: string) =>
    setBands((prev) =>
      prev.map((b, i) => (i === index ? { ...b, [key]: value } : b)),
    );

  const addBand = () => setBands((prev) => [...prev, emptyBand()]);
  const removeBand = (index: number) =>
    setBands((prev) => prev.filter((_, i) => i !== index));

  const onSubmit = async () => {
    setErrorBanner(null);
    const bandError = validateBands(bands);
    if (bandError) {
      setErrorBanner(bandError);
      return;
    }
    const rows = bands.map((b) => ({
      tenant_id: tenantId,
      transaction_type: scope.transaction_type,
      // Commission is keyed WITHOUT account_type (CommissionConfigCreateRequest
      // has no such field) — do not send it.
      currency: scope.currency.toUpperCase(),
      user_type: scope.user_type === "all" ? null : (scope.user_type as UserType),
      amount_from: orNull(b.amount_from),
      amount_to: orNull(b.amount_to),
      fixed_commission: b.fixed.trim() || "0",
      variable_commission_pct: b.variable_pct.trim() || "0",
      commission_cap: orNull(b.cap),
    }));
    setSubmitting(true);
    const result = reviseRequest
      ? await reviseAndResubmitConfigRequestAction(tenantId, reviseRequest.id, {
          bands: rows,
        })
      : editConfig
        ? await proposeCommissionUpdateAction(tenantId, editConfig.id, {
            bands: rows,
          })
        : await proposeCommissionBandsAction(tenantId, { bands: rows });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: reviseRequest
        ? "Resubmitted for approval"
        : "Change proposed — pending approval",
      description: `${scope.transaction_type} · ${scope.currency} · ${rows.length} band${rows.length === 1 ? "" : "s"}`,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {reviseRequest
              ? "Revise commission schedule"
              : editMode
                ? "Edit commission"
                : "New commission schedule"}
          </DialogTitle>
          <DialogDescription>
            Per band, commission = fixed + min(variable% × amount, cap). Changes
            are proposed and go live after a second admin approves.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[62vh] space-y-4 overflow-y-auto pr-1">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="c-txn">Service</Label>
              <Select
                value={scope.transaction_type}
                onValueChange={(v) => updateScope("transaction_type", v)}
                disabled={scopeLocked || services.length === 0}
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
                value={scope.currency}
                onValueChange={(v) => updateScope("currency", v)}
                disabled={scopeLocked || instruments.length === 0}
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
                value={scope.user_type}
                onValueChange={(v) => updateScope("user_type", v)}
                disabled={scopeLocked}
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

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Bands</Label>
              <Button variant="outline" size="sm" onClick={addBand}>
                <Plus className="h-3.5 w-3.5" />
                Add band
              </Button>
            </div>
            {bands.map((band, i) => {
              const preview = bandPreview(band);
              return (
                <div key={i} className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">
                      Band {i + 1}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove band ${i + 1}`}
                      disabled={bands.length === 1}
                      onClick={() => removeBand(i)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </div>
                  <div className="grid grid-cols-5 gap-2">
                    <div>
                      <Label htmlFor={`c-from-${i}`} className="text-[11px]">
                        From
                      </Label>
                      <Input
                        id={`c-from-${i}`}
                        value={band.amount_from}
                        onChange={(e) => updateBand(i, "amount_from", e.target.value)}
                        placeholder="0"
                      />
                    </div>
                    <div>
                      <Label htmlFor={`c-to-${i}`} className="text-[11px]">
                        To
                      </Label>
                      <Input
                        id={`c-to-${i}`}
                        value={band.amount_to}
                        onChange={(e) => updateBand(i, "amount_to", e.target.value)}
                        placeholder="∞"
                      />
                    </div>
                    <div>
                      <Label htmlFor={`c-fixed-${i}`} className="text-[11px]">
                        Fixed
                      </Label>
                      <Input
                        id={`c-fixed-${i}`}
                        value={band.fixed}
                        onChange={(e) => updateBand(i, "fixed", e.target.value)}
                        placeholder="2"
                      />
                    </div>
                    <div>
                      <Label htmlFor={`c-var-${i}`} className="text-[11px]">
                        Variable %
                      </Label>
                      <Input
                        id={`c-var-${i}`}
                        value={band.variable_pct}
                        onChange={(e) => updateBand(i, "variable_pct", e.target.value)}
                        placeholder="0.01"
                      />
                    </div>
                    <div>
                      <Label htmlFor={`c-cap-${i}`} className="text-[11px]">
                        Cap
                      </Label>
                      <Input
                        id={`c-cap-${i}`}
                        value={band.cap}
                        onChange={(e) => updateBand(i, "cap", e.target.value)}
                        placeholder="25"
                      />
                    </div>
                  </div>
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    On a sample {preview.sample.toFixed(2)} transaction,
                    commission ≈{" "}
                    <span className="text-foreground">{preview.commission}</span>.
                  </p>
                </div>
              );
            })}
            <p className="text-[10px] text-muted-foreground">
              Variable % is a decimal (0.01 = 1%). Leave the last band&apos;s
              &ldquo;To&rdquo; blank for an open-ended top band.
            </p>
          </div>

          {errorBanner && (
            <ErrorBanner
              title={reviseRequest ? "Couldn't resubmit" : "Couldn't propose"}
              description={errorBanner}
            />
          )}
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
