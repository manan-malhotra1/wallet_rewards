/**
 * <CreateCampaignDialog> — create-campaign wizard with an optional inline
 * budget.
 *
 * Step 1: pick the campaign type. Step 2: configure type-specific fields
 * plus an optional "Set a per-campaign budget" section. The dialog
 * submits via `createCampaignWithBudgetAction` — the campaign is
 * created first, then the budget if requested. A budget-create failure
 * does NOT undo the campaign; the dialog surfaces the budget error so
 * the operator can fix it on the /budgets page without re-entering the
 * campaign.
 */
"use client";

import { Coins, PiggyBank } from "lucide-react";
import * as React from "react";

import { createCampaignWithBudgetAction } from "@/app/(authenticated)/campaigns/_actions";
import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";

import type { Rule, Service } from "@/lib/api-types";

const RULE_TYPES: { value: Rule["rule_type"]; label: string; help: string }[] = [
  { value: "milestone", label: "Milestone", help: "User completes N qualifying txns" },
  { value: "streak", label: "Streak", help: "N consecutive periods without break" },
  { value: "first_time", label: "First-time", help: "Fires once on first occurrence" },
  { value: "value_based", label: "Value-based", help: "Triggers above a min amount" },
  { value: "composite", label: "Composite", help: "Multiple conditions joined AND / OR" },
  { value: "campaign", label: "Time-boxed", help: "Runs between a start + end date" },
  { value: "referral", label: "Referral", help: "Referrer rewarded on referred action" },
];

type BudgetWindow = "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";

interface BudgetPreset {
  key: string;
  label: string;
  description: string;
  cap_amount: string;
  window_type: BudgetWindow;
}

const POINTS_PRESETS: BudgetPreset[] = [
  {
    key: "conservative",
    label: "Conservative",
    description: "1,000 pts / day",
    cap_amount: "1000",
    window_type: "rolling_24h",
  },
  {
    key: "standard",
    label: "Standard",
    description: "10,000 pts / day",
    cap_amount: "10000",
    window_type: "rolling_24h",
  },
  {
    key: "monthly",
    label: "Monthly cap",
    description: "100,000 pts / month",
    cap_amount: "100000",
    window_type: "calendar_month",
  },
  {
    key: "lifetime",
    label: "Lifetime cap",
    description: "1,000,000 pts total",
    cap_amount: "1000000",
    window_type: "lifetime",
  },
];

const CASHBACK_PRESETS: BudgetPreset[] = [
  {
    key: "conservative",
    label: "Conservative",
    description: "1,000 / day",
    cap_amount: "1000",
    window_type: "rolling_24h",
  },
  {
    key: "standard",
    label: "Standard",
    description: "10,000 / day",
    cap_amount: "10000",
    window_type: "rolling_24h",
  },
  {
    key: "monthly",
    label: "Monthly cap",
    description: "100,000 / month",
    cap_amount: "100000",
    window_type: "calendar_month",
  },
  {
    key: "lifetime",
    label: "Lifetime cap",
    description: "1,000,000 total",
    cap_amount: "1000000",
    window_type: "lifetime",
  },
];

interface FormState {
  name: string;
  description: string;
  rule_type: Rule["rule_type"];
  transaction_type: string;
  count_threshold: string;
  min_amount: string;
  time_window: string;
  // Epic 10 — type-specific fields
  streak_units: string;
  streak_unit_window: "day" | "week";
  campaign_start_date: string;
  campaign_end_date: string;
  reward_type: Rule["reward_type"];
  reward_value: string;
  stop_after_n_triggers: string;
  resets_after_trigger: boolean;
  // Budget section ---------------------------------------------------
  budget_enabled: boolean;
  budget_preset: string;
  budget_cap_amount: string;
  budget_window_type: BudgetWindow;
}

const INITIAL: FormState = {
  name: "",
  description: "",
  rule_type: "milestone",
  transaction_type: "p2p",
  count_threshold: "",
  min_amount: "",
  time_window: "",
  streak_units: "3",
  streak_unit_window: "day",
  campaign_start_date: "",
  campaign_end_date: "",
  reward_type: "points",
  reward_value: "",
  stop_after_n_triggers: "",
  resets_after_trigger: true,
  budget_enabled: false,
  budget_preset: "standard",
  budget_cap_amount: "10000",
  budget_window_type: "rolling_24h",
};

const WINDOW_LABEL: Record<BudgetWindow, string> = {
  rolling_24h: "rolling 24h",
  rolling_7d: "rolling 7d",
  calendar_month: "calendar month",
  lifetime: "lifetime",
};

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
  if (form.rule_type === "streak") {
    const n = form.streak_units || "N";
    return `When a user does ${form.transaction_type} ${n} ${form.streak_unit_window}s in a row, ${reward}.`;
  }
  if (form.rule_type === "campaign") {
    const start = form.campaign_start_date || "(start)";
    const end = form.campaign_end_date || "(end)";
    return `Between ${start} and ${end}, a user's first ${form.transaction_type} ${reward}.`;
  }
  return `Campaign type: ${form.rule_type}. ${reward}.`;
}

function summariseBudget(form: FormState): string {
  if (!form.budget_enabled) {
    return "No per-campaign budget — campaign relies on the tenant-wide budget if set, else runs uncapped.";
  }
  const cap = form.budget_cap_amount || "?";
  const unit = form.reward_type === "points" ? "pts" : "(reward units)";
  return `Cap ${cap} ${unit} per ${WINDOW_LABEL[form.budget_window_type]}.`;
}

export function CreateCampaignDialog({
  tenantId,
  services,
  trigger,
}: {
  tenantId: string;
  services: Service[];
  trigger: React.ReactNode;
}) {
  const initialWithService: FormState = {
    ...INITIAL,
    transaction_type: services[0]?.code ?? INITIAL.transaction_type,
  };
  const [open, setOpen] = React.useState(false);
  const [step, setStep] = React.useState<1 | 2>(1);
  const [form, setForm] = React.useState<FormState>(initialWithService);
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setStep(1);
      setForm(initialWithService);
      setErrorBanner(null);
    }
    // initialWithService depends only on services prop — captured at render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const applyPreset = (preset: BudgetPreset) =>
    setForm((prev) => ({
      ...prev,
      budget_preset: preset.key,
      budget_cap_amount: preset.cap_amount,
      budget_window_type: preset.window_type,
    }));

  const presets = form.reward_type === "points" ? POINTS_PRESETS : CASHBACK_PRESETS;

  const onSubmit = async (status: "active" | "draft") => {
    setErrorBanner(null);
    if (!form.name || !form.reward_value) {
      setErrorBanner("Name and reward value are required.");
      return;
    }
    if (form.budget_enabled) {
      const cap = parseFloat(form.budget_cap_amount);
      if (!Number.isFinite(cap) || cap <= 0) {
        setErrorBanner("Budget cap must be a positive number.");
        return;
      }
    }
    setSubmitting(true);
    const result = await createCampaignWithBudgetAction(
      {
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
        // Epic 10 — only thread these when the rule type uses them; the
        // backend validator rejects e.g. streak_units on a first_time rule.
        streak_units:
          form.rule_type === "streak" && form.streak_units
            ? Number(form.streak_units)
            : undefined,
        streak_unit_window:
          form.rule_type === "streak" ? form.streak_unit_window : undefined,
        campaign_start_date:
          form.rule_type === "campaign" ? form.campaign_start_date : undefined,
        campaign_end_date:
          form.rule_type === "campaign" ? form.campaign_end_date : undefined,
        reward_type: form.reward_type,
        reward_value: form.reward_value,
        stop_after_n_triggers: form.stop_after_n_triggers
          ? Number(form.stop_after_n_triggers)
          : undefined,
        resets_after_trigger: form.resets_after_trigger,
      },
      form.budget_enabled
        ? {
            cap_amount: form.budget_cap_amount,
            window_type: form.budget_window_type,
          }
        : undefined,
    );
    setSubmitting(false);
    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    if (form.budget_enabled && !result.budgetCreated) {
      // Campaign landed, budget didn't — toast the campaign success +
      // surface the budget error so the operator can pick up on
      // /budgets without re-entering the whole campaign.
      toast({
        title: "Campaign created, but budget failed",
        description:
          result.budgetError ?? "Open the Budgets page to add it manually.",
        variant: "danger",
      });
      setOpen(false);
      return;
    }
    toast({
      title:
        status === "active"
          ? form.budget_enabled
            ? "Campaign + budget activated"
            : "Campaign activated"
          : "Campaign saved as draft",
      description: form.name,
    });
    setOpen(false);
  };

  const selectedType = RULE_TYPES.find((t) => t.value === form.rule_type);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Create campaign{step === 2 && selectedType ? ` · ${selectedType.label}` : ""}
          </DialogTitle>
          <DialogDescription>
            {step === 1
              ? "Pick the campaign type. Each type unlocks a different set of fields."
              : "Configure the fields. Summary at the bottom updates live."}
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
                className="rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary hover:bg-accent"
              >
                <div className="text-sm font-semibold">{t.label}</div>
                <div className="mt-1 text-xs text-muted-foreground">{t.help}</div>
              </button>
            ))}
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            {/* --- Core rule fields ----------------------------------- */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="Weekly P2P milestone"
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="txn-type">Service</Label>
                <Select
                  value={form.transaction_type}
                  onValueChange={(v) => update("transaction_type", v)}
                  disabled={services.length === 0}
                >
                  <SelectTrigger id="txn-type" className="mt-1">
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
              {form.rule_type === "milestone" && (
                <div>
                  <Label htmlFor="count">Count threshold</Label>
                  <Input
                    id="count"
                    type="number"
                    value={form.count_threshold}
                    onChange={(e) => update("count_threshold", e.target.value)}
                    placeholder="5"
                    className="mt-1"
                  />
                </div>
              )}
              {form.rule_type === "streak" && (
                <>
                  <div>
                    <Label htmlFor="streak-units">Consecutive periods</Label>
                    <Input
                      id="streak-units"
                      type="number"
                      min="2"
                      value={form.streak_units}
                      onChange={(e) => update("streak_units", e.target.value)}
                      placeholder="3"
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="streak-window">Period unit</Label>
                    <div className="mt-1">
                      <Select
                        value={form.streak_unit_window}
                        onValueChange={(v) =>
                          update("streak_unit_window", v as "day" | "week")
                        }
                      >
                        <SelectTrigger id="streak-window">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="day">Day</SelectItem>
                          <SelectItem value="week">Week</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </>
              )}
              {form.rule_type === "campaign" && (
                <>
                  <div>
                    <Label htmlFor="camp-start">Start date</Label>
                    <Input
                      id="camp-start"
                      type="date"
                      value={form.campaign_start_date}
                      onChange={(e) =>
                        update("campaign_start_date", e.target.value)
                      }
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="camp-end">End date</Label>
                    <Input
                      id="camp-end"
                      type="date"
                      value={form.campaign_end_date}
                      onChange={(e) =>
                        update("campaign_end_date", e.target.value)
                      }
                      className="mt-1"
                    />
                  </div>
                </>
              )}
              {(form.rule_type === "value_based" || form.rule_type === "milestone") && (
                <div>
                  <Label htmlFor="min-amount">Min amount</Label>
                  <Input
                    id="min-amount"
                    value={form.min_amount}
                    onChange={(e) => update("min_amount", e.target.value)}
                    placeholder="1000.00"
                    className="mt-1"
                  />
                </div>
              )}
              {(form.rule_type === "milestone" || form.rule_type === "streak") && (
                <div>
                  <Label htmlFor="window">Time window</Label>
                  <div className="mt-1">
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
                </div>
              )}
              <div>
                <Label htmlFor="reward-type">Reward type</Label>
                <div className="mt-1">
                  <Select
                    value={form.reward_type}
                    onValueChange={(v) =>
                      update("reward_type", v as Rule["reward_type"])
                    }
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
              </div>
              <div>
                <Label htmlFor="reward-value">Reward value</Label>
                <Input
                  id="reward-value"
                  value={form.reward_value}
                  onChange={(e) => update("reward_value", e.target.value)}
                  placeholder="200"
                  className="mt-1"
                />
              </div>
              <div className="col-span-2">
                <Label htmlFor="stop-after">
                  Stop after N triggers (0 = unlimited)
                </Label>
                <Input
                  id="stop-after"
                  type="number"
                  value={form.stop_after_n_triggers}
                  onChange={(e) => update("stop_after_n_triggers", e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>

            {/* --- Inline budget section ----------------------------- */}
            <div className="rounded-lg border bg-card">
              <label className="flex cursor-pointer items-start gap-3 p-4">
                <input
                  type="checkbox"
                  checked={form.budget_enabled}
                  onChange={(e) => update("budget_enabled", e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-input accent-[--color-primary]"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <PiggyBank className="h-4 w-4 text-primary" />
                    <span className="text-sm font-semibold text-foreground">
                      Set a per-campaign budget
                    </span>
                    <Badge variant="info" className="text-[10px]">
                      Optional
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Caps reward issuance for THIS campaign. Layers with any
                    tenant-wide budget — both must pass.
                  </p>
                </div>
              </label>

              {form.budget_enabled && (
                <div className="space-y-4 border-t bg-muted/20 p-4">
                  <div>
                    <Label>Preset</Label>
                    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {presets.map((preset) => {
                        const active = form.budget_preset === preset.key;
                        return (
                          <button
                            key={preset.key}
                            type="button"
                            onClick={() => applyPreset(preset)}
                            className={cn(
                              "rounded-md border bg-card px-3 py-2 text-left transition-colors",
                              active
                                ? "border-primary bg-primary/5 ring-1 ring-primary"
                                : "hover:border-primary/40 hover:bg-accent",
                            )}
                          >
                            <div className="text-xs font-semibold">{preset.label}</div>
                            <div className="mt-0.5 text-[11px] text-muted-foreground">
                              {preset.description}
                            </div>
                          </button>
                        );
                      })}
                      <button
                        type="button"
                        onClick={() => update("budget_preset", "custom")}
                        className={cn(
                          "rounded-md border bg-card px-3 py-2 text-left transition-colors",
                          form.budget_preset === "custom"
                            ? "border-primary bg-primary/5 ring-1 ring-primary"
                            : "hover:border-primary/40 hover:bg-accent",
                        )}
                      >
                        <div className="text-xs font-semibold">Custom</div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          Set your own
                        </div>
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <Label htmlFor="budget-cap">Cap amount</Label>
                      <Input
                        id="budget-cap"
                        value={form.budget_cap_amount}
                        onChange={(e) => {
                          update("budget_cap_amount", e.target.value);
                          update("budget_preset", "custom");
                        }}
                        placeholder="10000"
                        className="mt-1"
                      />
                    </div>
                    <div>
                      <Label htmlFor="budget-window">Window</Label>
                      <div className="mt-1">
                        <Select
                          value={form.budget_window_type}
                          onValueChange={(v) => {
                            update("budget_window_type", v as BudgetWindow);
                            update("budget_preset", "custom");
                          }}
                        >
                          <SelectTrigger id="budget-window">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="rolling_24h">Rolling 24h</SelectItem>
                            <SelectItem value="rolling_7d">Rolling 7d</SelectItem>
                            <SelectItem value="calendar_month">
                              Calendar month
                            </SelectItem>
                            <SelectItem value="lifetime">Lifetime</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* --- Summary footer ------------------------------------ */}
            <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="flex items-start gap-2">
                <Coins className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                <span>{summarise(form)}</span>
              </div>
              <div className="flex items-start gap-2">
                <PiggyBank className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                <span>{summariseBudget(form)}</span>
              </div>
            </div>

            {errorBanner && (
              <ErrorBanner title="Couldn't create" description={errorBanner} />
            )}
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
                {submitting ? "Saving…" : "Activate campaign"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
