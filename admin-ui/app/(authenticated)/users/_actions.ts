"use server";

/**
 * Server actions for the Users page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { adminResetPin } from "@/lib/api-endpoints";

export type PinResetActionResult =
  | { ok: true; deliveredVia: "inline" | "sms"; newPin: string | null }
  | { ok: false; errorCode: string; message: string };

/**
 * Generate a fresh random PIN for the user. The plaintext PIN comes
 * back in the response so the admin can read it back to the user
 * over a verified channel — Phase 2 will route this through the
 * notifications module for SMS delivery, at which point the response
 * will return delivered_via='sms' and newPin=null.
 */
export async function resetUserPinAction(
  userId: string,
  tenantId: string,
): Promise<PinResetActionResult> {
  try {
    const res = await adminResetPin(userId, tenantId);
    revalidatePath("/users");
    return {
      ok: true,
      deliveredVia: res.delivered_via,
      newPin: res.new_pin,
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
