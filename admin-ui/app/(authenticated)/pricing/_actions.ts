/**
 * Server actions for the Pricing screen (Epic 24 / Story 24.1).
 *
 * Since Epic 22 all pricing writes go through the maker-checker pipeline:
 * these actions PROPOSE a create/delete via `POST /config-requests` (status
 * PENDING). The change only goes live once a second admin approves it in the
 * config-requests review UI (Story 24.3).
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";

export type PricingActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/**
 * Propose creating a pricing SCHEDULE (Epic 25). The payload is a multi-band
 * set: `{ bands: [ <full create row>, … ] }`, where each row repeats the
 * shared scope. Nothing goes live until a second admin approves.
 */
export async function proposePricingBandsAction(
  tenantId: string,
  payload: { bands: Record<string, unknown>[] },
): Promise<PricingActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "pricing",
      operation: "create",
      payload,
    });
    revalidatePath("/pricing");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a pricing config by id. Returns the standard {ok} result. */
export async function proposePricingDeleteAction(
  configId: string,
  tenantId: string,
): Promise<PricingActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "pricing",
      operation: "delete",
      target_config_id: configId,
    });
    revalidatePath("/pricing");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): PricingActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
