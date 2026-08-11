/**
 * <CreateMultiplierDialog> — form for POST /multipliers (Epic 10 / WAL-78).
 *
 * Scope defaults to tenant-wide (every rule, every user); the operator can
 * narrow it to one points rule and/or one segment. The validity window is
 * optional on both ends — an empty window means "always active".
 */
"use client";

import * as React from "react";

import { createMultiplierAction } from "@/app/(authenticated)/multipliers/_actions";
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
import type { Rule, Segment } from "@/lib/api-types";

// Radix Select items can't carry an empty-string value, so the "no scope"
// choice uses a sentinel that is translated to an omitted field on submit.
const ALL = "__all__";

interface FormState {
  multiplier: string;
  rule_id: string;
  segment_id: string;
  valid_from: string;
  valid_until: string;
}

const INITIAL: FormState = {
  multiplier: "",
  rule_id: ALL,
  segment_id: ALL,
  valid_from: "",
  valid_until: "",
};

/** Human summary of the configured boost, mirrored live under the form. */
function summarise(form: FormState, rules: Rule[], segments: Segment[]): string {
  const factor = form.multiplier || "N";
  const rule =
    form.rule_id === ALL
      ? "every points rule"
      : `"${rules.find((r) => r.id === form.rule_id)?.name ?? "?"}"`;
  const seg =
    form.segment_id === ALL
      ? "all users"
      : `users in "${segments.find((s) => s.id === form.segment_id)?.name ?? "?"}"`;
  const window =
    form.valid_from || form.valid_until
      ? ` between ${form.valid_from || "now"} and ${form.valid_until || "forever"}`
      : "";
  return `${factor}× points on ${rule} for ${seg}${window}. If multipliers overlap, only the highest applies.`;
}

export function CreateMultiplierDialog({
  tenantId,
  rules,
  segments,
  trigger,
}: {
  tenantId: string;
  rules: Rule[];
  segments: Segment[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Multipliers only boost points issuance — cashback rules pay face value —
  // so the rule picker hides cashback rules entirely.
  const pointsRules = rules.filter((r) => r.reward_type === "points");

  React.useEffect(() => {
    if (!open) {
      setForm(INITIAL);
      setError(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setError(null);
    const factor = Number(form.multiplier);
    // 999.99 mirrors the backend column precision (Numeric(5,2)).
    if (!Number.isFinite(factor) || factor <= 0 || factor > 999.99) {
      setError("Factor must be a positive number up to 999.99, e.g. 2 or 1.5.");
      return;
    }
    if (
      form.valid_from &&
      form.valid_until &&
      form.valid_from >= form.valid_until
    ) {
      setError("Start must be strictly before end.");
      return;
    }
    setSubmitting(true);
    const res = await createMultiplierAction({
      tenant_id: tenantId,
      rule_id: form.rule_id === ALL ? undefined : form.rule_id,
      segment_id: form.segment_id === ALL ? undefined : form.segment_id,
      multiplier: form.multiplier,
      // datetime-local values are naive local time; toISOString pins them to
      // an explicit UTC instant so the backend never guesses a timezone.
      valid_from: form.valid_from
        ? new Date(form.valid_from).toISOString()
        : undefined,
      valid_until: form.valid_until
        ? new Date(form.valid_until).toISOString()
        : undefined,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Multiplier created", description: `${form.multiplier}× points` });
      setOpen(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New bonus multiplier</DialogTitle>
          <DialogDescription>
            Boosts the points value of matching rewards at issuance time.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="w-40">
            <Label htmlFor="mult-factor">Factor</Label>
            <Input
              id="mult-factor"
              type="number"
              min="0"
              step="0.5"
              value={form.multiplier}
              onChange={(e) => update("multiplier", e.target.value)}
              placeholder="2"
              className="mt-1 font-mono tabular-nums"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="mult-rule">Rule scope</Label>
              <div className="mt-1">
                <Select
                  value={form.rule_id}
                  onValueChange={(v) => update("rule_id", v)}
                >
                  <SelectTrigger id="mult-rule">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All points rules</SelectItem>
                    {pointsRules.map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {r.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label htmlFor="mult-segment">Segment scope</Label>
              <div className="mt-1">
                <Select
                  value={form.segment_id}
                  onValueChange={(v) => update("segment_id", v)}
                >
                  <SelectTrigger id="mult-segment">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>All users</SelectItem>
                    {segments.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="mult-from">Starts (optional)</Label>
              <Input
                id="mult-from"
                type="datetime-local"
                value={form.valid_from}
                onChange={(e) => update("valid_from", e.target.value)}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="mult-until">Ends (optional)</Label>
              <Input
                id="mult-until"
                type="datetime-local"
                value={form.valid_until}
                onChange={(e) => update("valid_until", e.target.value)}
                className="mt-1"
              />
            </div>
          </div>

          <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
            {summarise(form, pointsRules, segments)}
          </div>

          {error && <ErrorBanner title="Couldn't create" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Creating…" : "Create multiplier"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
