"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createBudget,
  deleteBudget,
  type CreateBudgetPayload,
} from "@/lib/api-endpoints";

export type BudgetActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function createBudgetAction(
  payload: CreateBudgetPayload,
): Promise<BudgetActionResult> {
  try {
    await createBudget(payload);
    revalidatePath("/budgets");
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

export async function deleteBudgetAction(
  budgetId: string,
  tenantId: string,
): Promise<BudgetActionResult> {
  try {
    await deleteBudget(budgetId, tenantId);
    revalidatePath("/budgets");
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
