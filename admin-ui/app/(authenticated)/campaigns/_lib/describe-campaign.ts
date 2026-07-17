/**
 * Compose a plain-English description of a campaign + its configuration.
 * Used by the tooltip on the campaigns table — shows everything an
 * operator would want to verify at a glance.
 */
import type { Rule, RulePerformance } from "@/lib/api-types";

const BUDGET_SCOPE_LABEL: Record<RulePerformance["budget_scope"], string> = {
  none: "No budget — campaign runs uncapped.",
  tenant_only: "Budget: tenant-wide cap only.",
  rule_only: "Budget: per-campaign cap only.",
  both: "Budget: both per-campaign cap AND tenant-wide cap (both must pass).",
};

const TIME_WINDOW_LABEL: Record<string, string> = {
  lifetime: "lifetime",
  calendar_month: "calendar month",
  rolling_7d: "rolling 7 days",
};

/**
 * Return a 1–2 sentence summary of what triggers this campaign.
 * No budget — that's the second line in the tooltip.
 */
export function describeTrigger(rule: Rule): string {
  const txn = rule.transaction_type ?? "transaction";
  const reward = `credits ${rule.reward_value} ${rule.reward_type}`;

  switch (rule.rule_type) {
    case "first_time":
      return `On the user's first ${txn}, ${reward}. Fires once per user.`;
    case "milestone": {
      const n = rule.count_threshold ?? "N";
      const win = rule.time_window
        ? `in any ${TIME_WINDOW_LABEL[rule.time_window] ?? rule.time_window}`
        : "lifetime";
      return `When a user completes ${n} ${txn} transactions ${win}, ${reward}.`;
    }
    case "value_based": {
      const min = rule.min_amount ?? "(min amount)";
      return `Each time a user's ${txn} is ≥ ${min}, ${reward}.`;
    }
    case "streak": {
      const n = rule.streak_units ?? "N";
      const unit = rule.streak_unit_window ?? "day";
      return `When a user does ${txn} ${n} ${unit}s in a row, ${reward}.`;
    }
    case "campaign": {
      const start = rule.campaign_start_date ?? "(start)";
      const end = rule.campaign_end_date ?? "(end)";
      return `Between ${start} and ${end}, on a user's first qualifying ${txn}, ${reward}.`;
    }
    case "composite": {
      const op = rule.composite_operator ?? "AND";
      const parts = (rule.conditions ?? []).map(
        (c) => `${c.count_threshold}× ${c.transaction_type}`,
      );
      const joined = parts.length ? parts.join(` ${op} `) : "multiple conditions";
      return `Composite (${joined}) — ${reward}.`;
    }
    case "referral": {
      const trigger =
        rule.referral_trigger === "nth_transaction"
          ? `the referred user's ${rule.referral_trigger_n ?? "N"}th txn`
          : "the referred user's signup";
      const referee = rule.referee_reward_value
        ? ` Referee gets ${rule.referee_reward_value} ${rule.reward_type}.`
        : "";
      return `Referral — on ${trigger}, referrer ${reward}.${referee}`;
    }
    default:
      return `${rule.rule_type} rule — ${reward}.`;
  }
}

/** Friendly label for the budget scope, used directly in the table cell. */
export function describeBudgetScope(
  scope: RulePerformance["budget_scope"],
): string {
  return BUDGET_SCOPE_LABEL[scope];
}

/**
 * Compose a multi-line description used by the tooltip. Includes the
 * trigger, reward, recurrence flags, and the budget scope.
 */
export function describeCampaignFull(
  rule: Rule,
  performance: RulePerformance | null,
): string[] {
  const lines: string[] = [];
  lines.push(describeTrigger(rule));

  if (rule.stop_after_n_triggers) {
    lines.push(`Caps at ${rule.stop_after_n_triggers} fires per user.`);
  }
  if (rule.rule_type === "milestone" || rule.rule_type === "streak") {
    lines.push(
      rule.resets_after_trigger
        ? "Counter resets after each fire."
        : "Counter does not reset (fires only once).",
    );
  }
  if (performance) {
    lines.push(describeBudgetScope(performance.budget_scope));
  }
  return lines;
}
