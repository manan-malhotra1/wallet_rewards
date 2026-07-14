/**
 * Server actions for the Commissions screen (Epic 24 / Story 24.2).
 *
 * All commission writes go through the maker-checker pipeline: these
 * actions PROPOSE a create/delete via `POST /config-requests` (status
 * PENDING). Approval by a second admin (Story 24.3) applies the change.
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";
import type { UserType } from "@/lib/api-types";

export type CommissionActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Fields the commission create dialog collects (money values are strings). */
export interface ProposeCommissionInput {
  tenant_id: string;
  transaction_type: string;
  currency: string;
  user_type: UserType | null;
  amount_from?: string;
  amount_to?: string;
  fixed_commission: string;
  variable_commission_pct: string;
  commission_cap?: string;
}

/** Propose creating a commission config. */
export async function proposeCommissionChangeAction(
  input: ProposeCommissionInput,
): Promise<CommissionActionResult> {
  try {
    await proposeConfigChange(input.tenant_id, {
      config_type: "commission",
      operation: "create",
      payload: { ...input },
    });
    revalidatePath("/commissions");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a commission config by id. */
export async function proposeCommissionDeleteAction(
  configId: string,
  tenantId: string,
): Promise<CommissionActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "commission",
      operation: "delete",
      target_config_id: configId,
    });
    revalidatePath("/commissions");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): CommissionActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
