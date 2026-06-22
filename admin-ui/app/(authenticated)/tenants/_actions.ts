"use server";

/**
 * Server actions for the Tenants page.
 *
 * Wraps the backend PATCH /api/v1/tenants/{id} endpoint and revalidates
 * the page on success so the new identity-card values render without a
 * manual refresh.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { updateTenant, type UpdateTenantPayload } from "@/lib/api-endpoints";

export type TenantActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function updateTenantAction(
  tenantId: string,
  payload: UpdateTenantPayload,
): Promise<TenantActionResult> {
  try {
    await updateTenant(tenantId, payload);
    revalidatePath("/tenants");
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
