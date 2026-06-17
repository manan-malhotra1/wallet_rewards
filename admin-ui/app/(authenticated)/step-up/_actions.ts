"use server";

/**
 * Server actions for the Step-up PIN policies page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createStepUpPolicy,
  deleteStepUpPolicy,
  type CreateStepUpPolicyPayload,
} from "@/lib/api-endpoints";

export type StepUpActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function createStepUpPolicyAction(
  payload: CreateStepUpPolicyPayload,
): Promise<StepUpActionResult> {
  try {
    await createStepUpPolicy(payload);
    revalidatePath("/step-up");
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

export async function deleteStepUpPolicyAction(
  policyId: string,
  tenantId: string,
): Promise<StepUpActionResult> {
  try {
    await deleteStepUpPolicy(policyId, tenantId);
    revalidatePath("/step-up");
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
