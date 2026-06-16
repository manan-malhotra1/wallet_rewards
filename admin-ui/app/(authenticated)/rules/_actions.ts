"use server";

/**
 * Server actions for the Rules page.
 *
 * Wrap the typed API client so client components can submit the create-
 * rule form without exposing the backend URL or the admin JWT.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { createRule, type CreateRulePayload } from "@/lib/api-endpoints";

export type CreateRuleResult =
  | { ok: true; ruleId: string }
  | { ok: false; errorCode: string; message: string };

/**
 * Create a rule. Returns a `{ok: true, ruleId}` or a structured error so
 * the dialog can surface a toast / inline message without throwing.
 */
export async function createRuleAction(
  payload: CreateRulePayload,
): Promise<CreateRuleResult> {
  try {
    const rule = await createRule(payload);
    revalidatePath("/rules");
    return { ok: true, ruleId: rule.id };
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
