"use server";

/**
 * Server actions for the Bonus multipliers page (Epic 10 / WAL-78).
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createMultiplier,
  deleteMultiplier,
  type CreateMultiplierPayload,
} from "@/lib/api-endpoints";

export type MultiplierActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Map an unknown error to the shared action result shape. */
function toActionError(err: unknown): MultiplierActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}

/**
 * Create a bonus multiplier, then refresh the page data.
 *
 * Validation is re-done server-side (factor > 0, valid_from < valid_until)
 * so the action never trusts the client; the backend remains the final
 * authority and its 422s surface through the result.
 */
export async function createMultiplierAction(
  payload: CreateMultiplierPayload,
): Promise<MultiplierActionResult> {
  const factor = Number(payload.multiplier);
  // 999.99 mirrors the DB column (Numeric(5,2)) so an oversized factor is a
  // friendly 422 here instead of a raw 500 from the insert.
  if (!Number.isFinite(factor) || factor <= 0 || factor > 999.99) {
    return {
      ok: false,
      errorCode: "validation_error",
      message: "Multiplier factor must be a positive number up to 999.99.",
    };
  }
  // Compare as instants, not strings — mixed UTC offsets would break a
  // lexicographic comparison.
  if (
    payload.valid_from &&
    payload.valid_until &&
    new Date(payload.valid_from).getTime() >=
      new Date(payload.valid_until).getTime()
  ) {
    return {
      ok: false,
      errorCode: "validation_error",
      message: "Valid-from must be strictly before valid-until.",
    };
  }
  try {
    await createMultiplier(payload);
    revalidatePath("/multipliers");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}

/** Delete a multiplier (hard delete — future issuance stops immediately). */
export async function deleteMultiplierAction(
  multiplierId: string,
  tenantId: string,
): Promise<MultiplierActionResult> {
  try {
    await deleteMultiplier(multiplierId, tenantId);
    revalidatePath("/multipliers");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}
