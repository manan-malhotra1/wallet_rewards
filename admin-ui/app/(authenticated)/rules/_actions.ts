"use server";

/**
 * Server actions for the Rules page.
 *
 * `createRuleWithBudgetAction` is the wizard entrypoint — creates the
 * rule, optionally chains a rule-scoped budget. Failures are surfaced
 * structured so the dialog can render an inline error without losing
 * the rule the operator just created.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createBudget,
  createRule,
  type CreateBudgetPayload,
  type CreateRulePayload,
} from "@/lib/api-endpoints";

export interface InlineBudgetInput {
  cap_amount: string;
  window_type: "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";
}

export type CreateRuleResult =
  | { ok: true; ruleId: string; budgetCreated: boolean; budgetError?: string }
  | { ok: false; errorCode: string; message: string };

/**
 * Create a rule and optionally a rule-scoped budget atomically.
 *
 * Sequence:
 *   1. Create the rule. If THIS fails, nothing else happens; return error.
 *   2. If the form supplied a budget, create it. If THIS fails, the rule
 *      still exists — return success with `budgetCreated=false` +
 *      `budgetError` so the UI can prompt the operator to fix the
 *      budget separately without losing their rule.
 *
 * Currency for the budget is derived from `reward_type`:
 *   `points` → 'PTS', `cashback` → the rule's tenant base currency (we
 *   default to 'ZAR' here; tighten in Phase G+ when tenant currency is
 *   threaded through).
 */
export async function createRuleWithBudgetAction(
  rulePayload: CreateRulePayload,
  budget?: InlineBudgetInput,
): Promise<CreateRuleResult> {
  let rule;
  try {
    rule = await createRule(rulePayload);
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }

  revalidatePath("/rules");

  if (!budget) {
    return { ok: true, ruleId: rule.id, budgetCreated: false };
  }

  // Currency picks PTS for points rules; ZAR for cashback rules. The
  // tenant's real base currency will replace this default once a future
  // tenant-detail endpoint lands.
  const currency = rulePayload.reward_type === "points" ? "PTS" : "ZAR";

  const budgetPayload: CreateBudgetPayload = {
    tenant_id: rulePayload.tenant_id,
    scope_type: "rule",
    scope_id: rule.id,
    currency,
    window_type: budget.window_type,
    cap_amount: budget.cap_amount,
  };

  try {
    await createBudget(budgetPayload);
    revalidatePath("/budgets");
    return { ok: true, ruleId: rule.id, budgetCreated: true };
  } catch (err) {
    const message =
      err instanceof ApiError
        ? `${err.errorCode}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return {
      ok: true,
      ruleId: rule.id,
      budgetCreated: false,
      budgetError: message,
    };
  }
}

/**
 * @deprecated Prefer `createRuleWithBudgetAction` which handles both.
 * Kept for backward-compatibility with any external caller.
 */
export async function createRuleAction(
  payload: CreateRulePayload,
): Promise<CreateRuleResult> {
  return createRuleWithBudgetAction(payload, undefined);
}
