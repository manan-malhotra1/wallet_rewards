"use server";

/**
 * Server actions for the Reconciliation page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { triggerSweep } from "@/lib/api-endpoints";

export type SweepResult =
  | { ok: true; scanned: number; bumped: number; escalated: number }
  | { ok: false; errorCode: string; message: string };

/**
 * Kick off the pending-redemption sweep. Returns counts so the UI can
 * surface the outcome in a toast.
 */
export async function triggerSweepAction(
  tenantId: string,
  thresholdMinutes = 5,
): Promise<SweepResult> {
  try {
    const outcome = await triggerSweep({
      tenant_id: tenantId,
      threshold_minutes: thresholdMinutes,
    });
    revalidatePath("/reconciliation");
    return {
      ok: true,
      scanned: outcome.scanned_count,
      bumped: outcome.bumped_count,
      escalated: outcome.escalated_count,
    };
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
