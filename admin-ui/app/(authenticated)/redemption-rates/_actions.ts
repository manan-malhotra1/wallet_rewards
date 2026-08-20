"use server";

/**
 * Server actions for the Points rates page (Pay-PRD-1210/1280/1295).
 *
 * Conversion rates flow through the config maker-checker pipeline: these
 * actions PROPOSE a create/update/delete via `POST /config-requests` with
 * `config_type: "conversion_rate"`. The change only goes live once a second
 * admin approves it in the Configuration approvals tab.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";

export type ConversionRateActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Fields the rate dialog collects (numbers travel as strings). */
export interface ProposeConversionRateInput {
  tenant_id: string;
  currency: string;
  points_per_unit: string;
  value_per_unit: string;
  /** Anti-drain caps (Pay-PRD-1295) — omitted = uncapped on that axis. */
  max_points_per_txn?: string;
  max_balance_pct_per_txn?: string;
}

/** Propose creating a conversion rate. Nothing goes live until approved. */
export async function proposeConversionRateChangeAction(
  input: ProposeConversionRateInput,
): Promise<ConversionRateActionResult> {
  try {
    await proposeConfigChange(input.tenant_id, {
      config_type: "conversion_rate",
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
 * Propose UPDATING a live rate in place: the create-shaped payload plus the
 * `target_config_id` of the row being edited (its currency scope unchanged).
 */
export async function proposeConversionRateUpdateAction(
  tenantId: string,
  targetConfigId: string,
  payload: ProposeConversionRateInput,
): Promise<ConversionRateActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "conversion_rate",
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

/** Propose deleting a rate by id. Nothing is removed until approved. */
export async function proposeConversionRateDeleteAction(
  rateId: string,
  tenantId: string,
): Promise<ConversionRateActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "conversion_rate",
      operation: "delete",
      target_config_id: rateId,
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Revalidate the rates page + the approvals queue after a proposal. */
function revalidateAll() {
  revalidatePath("/redemption-rates");
  revalidatePath("/approvals");
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): ConversionRateActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
