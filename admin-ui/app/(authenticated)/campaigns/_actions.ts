"use server";

/**
 * Server actions for the Campaigns page.
 *
 * `createCampaignWithBudgetAction` is the wizard entrypoint — creates
 * the campaign (a rule on the backend), optionally chains a campaign-
 * scoped budget. Failures are surfaced structured so the dialog can
 * render an inline error without losing the campaign the operator just
 * created.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createBudget,
  createRule,
  deleteRule,
  updateRule,
  type CreateBudgetPayload,
  type CreateRulePayload,
  type UpdateRulePayload,
} from "@/lib/api-endpoints";

export interface InlineBudgetInput {
  cap_amount: string;
  window_type: "rolling_24h" | "rolling_7d" | "calendar_month" | "lifetime";
}

export type CreateCampaignResult =
  | {
      ok: true;
      campaignId: string;
      budgetCreated: boolean;
      budgetError?: string;
    }
  | { ok: false; errorCode: string; message: string };

/** @deprecated Use `CreateCampaignResult` — kept while callers migrate. */
export type CreateRuleResult = CreateCampaignResult;

/**
 * Create a campaign and optionally a campaign-scoped budget atomically.
 *
 * Sequence:
 *   1. Create the campaign. If THIS fails, nothing else happens; return error.
 *   2. If the form supplied a budget, create it. If THIS fails, the
 *      campaign still exists — return success with `budgetCreated=false`
 *      + `budgetError` so the UI can prompt the operator to fix the
 *      budget separately without losing their campaign.
 *
 * Currency for the inline budget is DERIVED from the campaign's reward,
 * never a separate input:
 *   `points`   → 'PTS' (points are always PTS)
 *   `cashback` → the campaign's `reward_currency` (a financial currency)
 */
export async function createCampaignWithBudgetAction(
  rulePayload: CreateRulePayload,
  budget?: InlineBudgetInput,
): Promise<CreateCampaignResult> {
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

  revalidatePath("/campaigns");

  if (!budget) {
    return { ok: true, campaignId: rule.id, budgetCreated: false };
  }

  const currency =
    rulePayload.reward_type === "points"
      ? "PTS"
      : (rulePayload.reward_currency ?? "ZAR");

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
    return { ok: true, campaignId: rule.id, budgetCreated: true };
  } catch (err) {
    const message =
      err instanceof ApiError
        ? `${err.errorCode}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return {
      ok: true,
      campaignId: rule.id,
      budgetCreated: false,
      budgetError: message,
    };
  }
}

/**
 * @deprecated Old name from before the Rule → Campaign rename. Kept
 * while the dialog is on the old import. Will be removed once the
 * dialog references `createCampaignWithBudgetAction` directly.
 */
export const createRuleWithBudgetAction = createCampaignWithBudgetAction;


export type CampaignMutationResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };


/** Patch a campaign's editable fields (name, description, reward, status). */
export async function updateCampaignAction(
  ruleId: string,
  tenantId: string,
  payload: UpdateRulePayload,
): Promise<CampaignMutationResult> {
  try {
    await updateRule(ruleId, tenantId, payload);
    revalidatePath("/campaigns");
    return { ok: true };
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
}


/** Soft-delete a campaign (status='inactive'). Idempotent. */
export async function deleteCampaignAction(
  ruleId: string,
  tenantId: string,
): Promise<CampaignMutationResult> {
  try {
    await deleteRule(ruleId, tenantId);
    revalidatePath("/campaigns");
    return { ok: true };
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
}
