"use server";

/**
 * Server actions for the Step-up PIN policies page.
 *
 * Step-up writes now flow through the maker-checker pipeline (the direct
 * create/delete step-up endpoints were retired on the backend). These actions
 * PROPOSE a create/update/delete via `POST /config-requests` with
 * `config_type: "step_up"` (status PENDING). The change only goes live once a
 * second admin approves it in the Configuration approvals tab.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";

export type StepUpActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Fields the step-up dialog collects (threshold is a string). */
export interface ProposeStepUpInput {
  tenant_id: string;
  transaction_type: "p2p" | "redemption";
  currency: string;
  threshold_amount: string;
}

/** Propose creating a step-up policy. Nothing goes live until approved. */
export async function proposeStepUpChangeAction(
  input: ProposeStepUpInput,
): Promise<StepUpActionResult> {
  try {
    await proposeConfigChange(input.tenant_id, {
      config_type: "step_up",
      operation: "create",
      payload: { ...input },
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Propose UPDATING a live step-up policy. Re-proposes the policy's values in
 * place: the create-shaped payload plus the `target_config_id` of the row being
 * edited (its transaction_type/currency scope unchanged). Approval by a second
 * admin applies the change.
 */
export async function proposeStepUpUpdateAction(
  tenantId: string,
  targetConfigId: string,
  payload: ProposeStepUpInput,
): Promise<StepUpActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "step_up",
      operation: "update",
      payload: { ...payload },
      target_config_id: targetConfigId,
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a step-up policy by id. Nothing is removed until approved. */
export async function proposeStepUpDeleteAction(
  policyId: string,
  tenantId: string,
): Promise<StepUpActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "step_up",
      operation: "delete",
      target_config_id: policyId,
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Revalidate the step-up page + the approvals queue after a proposal. */
function revalidateAll() {
  revalidatePath("/step-up");
  revalidatePath("/approvals");
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): StepUpActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
