/**
 * <CreateRuleDialog> — the create-rule wizard (2 steps in one dialog).
 *
 * Step 1: pick the rule type. Step 2: configure type-specific fields,
 * with a live summary sentence that updates as the form changes. Submits
 * via the `createRuleAction` server action.
 */
"use client";

import * as React from "react";

import { createRuleAction } from "@/app/(authenticated)/rules/_actions";
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

import type { Rule } from "@/lib/api-types";

const RULE_TYPES: { value: Rule["rule_type"]; label: string; help: string }[] = [
  { value: "milestone", label: "Milestone", help: "User completes N qualifying txns" },
  { value: "streak", label: "Streak", help: "N consecutive periods without break" },
  { value: "first_time", label: "First-time", help: "Fires once on first occurrence" },
  { value: "value_based", label: "Value-based", help: "Triggers above a min amount" },
  { value: "composite", label: "Composite", help: "Multiple conditions joined AND / OR" },
  { value: "campaign", label: "Campaign", help: "Time-boxed with start + end dates" },
  { value: "referral", label: "Referral", help: "Referrer rewarded on referred action" },
];

interface FormState {
  name: string;
  description: string;
  rule_type: Rule["rule_type"];
  transaction_type: string;
  count_threshold: string;
  min_amount: string;
  time_window: string;
  reward_type: Rule["reward_type"];
  reward_value: string;
  stop_after_n_triggers: string;
  resets_after_trigger: boolean;
}

const INITIAL: FormState = {
  name: "",
  description: "",
  rule_type: "milestone",
  transaction_type: "p2p",
  count_threshold: "",
  min_amount: "",
  time_window: "",
  reward_type: "points",
  reward_value: "",
  stop_after_n_triggers: "",
  resets_after_trigger: true,
};

/**
 * Build a one-sentence summary of the rule for the form footer. Keeps the
 * operator certain about what they're about to save.
 */
function summarise(form: FormState): string {
  const reward =
    form.reward_value && form.reward_type
      ? `credit ${form.reward_value} ${form.reward_type}`
      : "credit the configured reward";
  if (form.rule_type === "first_time") {
    return `When a user first ${form.transaction_type || "(action)"}s, ${reward}. Fires once.`;
  }
  if (form.rule_type === "milestone") {
    const count = form.count_threshold || "N";
    const win = form.time_window || "any window";
    return `When a user completes ${count} ${form.transaction_type} txns in ${win}, ${reward}.`;
  }
  if (form.rule_type === "value_based") {
    return `When a user's ${form.transaction_type} txn ≥ ${form.min_amount || "(amount)"}, ${reward}.`;
  }
  return `Rule type: ${form.rule_type}. ${reward}.`;
}

export function CreateRuleDialog({
  tenantId,
  trigger,
}: {
  tenantId: string;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [step, setStep] = React.useState<1 | 2>(1);
  const [form, setForm] = React.useState<FormState>(INITIAL);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Reset form when dialog opens/closes so a second invocation starts clean.
  React.useEffect(() => {
    if (!open) {
      setStep(1);
      setForm(INITIAL);
      setErrorBanner(null);
    }
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async (status: "active" | "draft") => {
    setErrorBanner(null);
    if (!form.name || !form.reward_value) {
      setErrorBanner("Name and reward value are required.");
      return;
    }
    setSubmitting(true);
    const result = await createRuleAction({
      tenant_id: tenantId,
      name: form.name,
      description: form.description || undefined,
      rule_type: form.rule_type,
      transaction_type: form.transaction_type,
      count_threshold: form.count_threshold
        ? Number(form.count_threshold)
        : undefined,
      min_amount: form.min_amount || undefined,
      time_window: form.time_window || undefined,
      reward_type: form.reward_type,
      reward_value: form.reward_value,
      stop_after_n_triggers: form.stop_after_n_triggers
        ? Number(form.stop_after_n_triggers)
        : undefined,
      resets_after_trigger: form.resets_after_trigger,
    });
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: status === "active" ? "Rule activated" : "Rule saved as draft",
      description: form.name,
    });
    setOpen(false);
  };

  const selectedType = RULE_TYPES.find((t) => t.value === form.rule_type);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            Create rule {step === 2 && selectedType ? `· ${selectedType.label}` : ""}
          </DialogTitle>
          <DialogDescription>
            {step === 1
              ? "Pick the rule type. Each type unlocks a different set of fields."
              : "Configure the fields. The summary below updates live."}
          </DialogDescription>
        </DialogHeader>

        {step === 1 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {RULE_TYPES.map((t) => (
              <button
                type="button"
                key={t.value}
                onClick={() => {
                  update("rule_type", t.value);
                  setStep(2);
                }}
                className="rounded-md border border-[--color-border] bg-[--color-surface-2] p-3 text-left hover:border-[--color-brand]"
              >
                <div className="text-[13px] font-semibold">{t.label}</div>
                <div className="mt-1 text-[11px] text-[--color-text-2]">{t.help}</div>
              </button>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="Weekly P2P milestone"
                />
              </div>
              <div>
                <Label htmlFor="txn-type">Transaction type</Label>
                <Input
                  id="txn-type"
                  value={form.transaction_type}
                  onChange={(e) => update("transaction_type", e.target.value)}
                  placeholder="p2p"
                />
              </div>
              {(form.rule_type === "milestone" || form.rule_type === "streak") && (
                <div>
                  <Label htmlFor="count">Count threshold</Label>
                  <Input
                    id="count"
                    type="number"
                    value={form.count_threshold}
                    onChange={(e) => update("count_threshold", e.target.value)}
                    placeholder="5"
                  />
                </div>
              )}
              {(form.rule_type === "value_based" || form.rule_type === "milestone") && (
                <div>
                  <Label htmlFor="min-amount">Min amount</Label>
                  <Input
                    id="min-amount"
                    value={form.min_amount}
                    onChange={(e) => update("min_amount", e.target.value)}
                    placeholder="1000.00"
                  />
                </div>
              )}
              {(form.rule_type === "milestone" || form.rule_type === "streak") && (
                <div>
                  <Label htmlFor="window">Time window</Label>
                  <Select
                    value={form.time_window}
                    onValueChange={(v) => update("time_window", v)}
                  >
                    <SelectTrigger id="window">
                      <SelectValue placeholder="Pick a window" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="calendar_month">Calendar month</SelectItem>
                      <SelectItem value="rolling_7d">Rolling 7 days</SelectItem>
                      <SelectItem value="rolling_30d">Rolling 30 days</SelectItem>
                      <SelectItem value="lifetime">Lifetime</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div>
                <Label htmlFor="reward-type">Reward type</Label>
                <Select
                  value={form.reward_type}
                  onValueChange={(v) => update("reward_type", v as Rule["reward_type"])}
                >
                  <SelectTrigger id="reward-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="points">Points</SelectItem>
                    <SelectItem value="cashback">Cashback</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="reward-value">Reward value</Label>
                <Input
                  id="reward-value"
                  value={form.reward_value}
                  onChange={(e) => update("reward_value", e.target.value)}
                  placeholder="200"
                />
              </div>
              <div>
                <Label htmlFor="stop-after">Stop after N triggers (0 = unlimited)</Label>
                <Input
                  id="stop-after"
                  type="number"
                  value={form.stop_after_n_triggers}
                  onChange={(e) => update("stop_after_n_triggers", e.target.value)}
                />
              </div>
            </div>
            <div className="rounded-md border border-[--color-border] bg-[--color-surface-2] p-3 text-[12px] text-[--color-text-2]">
              {summarise(form)}
            </div>
            {errorBanner && <ErrorBanner title="Couldn't create rule" description={errorBanner} />}
          </div>
        )}

        <DialogFooter>
          {step === 2 && (
            <Button variant="ghost" onClick={() => setStep(1)} disabled={submitting}>
              Back
            </Button>
          )}
          {step === 2 && (
            <>
              <Button
                variant="outline"
                onClick={() => onSubmit("draft")}
                disabled={submitting}
              >
                Save as draft
              </Button>
              <Button onClick={() => onSubmit("active")} disabled={submitting}>
                {submitting ? "Saving…" : "Activate rule"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
