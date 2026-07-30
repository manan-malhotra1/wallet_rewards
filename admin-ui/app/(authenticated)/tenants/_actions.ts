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
import {
  createTenant,
  updateTenant,
  updateTenantBranding,
  type CreateTenantPayload,
  type UpdateTenantPayload,
} from "@/lib/api-endpoints";
import type { TenantBranding } from "@/lib/api-types";

export type TenantActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Result of a create — carries the new tenant id so the UI can react. */
export type CreateTenantActionResult =
  | { ok: true; id: string }
  | { ok: false; errorCode: string; message: string };

/**
 * Provision a new tenant (platform-admin). Revalidates the tenants list and
 * the authenticated layout on success — the tenant switcher and any
 * tenant-derived theme both re-render once the new tenant exists.
 *
 * A 409 (duplicate name) is remapped to a friendly message; every other
 * `ApiError` surfaces its backend `error_code` / `message` verbatim.
 */
export async function createTenantAction(
  payload: CreateTenantPayload,
): Promise<CreateTenantActionResult> {
  try {
    const tenant = await createTenant(payload);
    revalidatePath("/tenants");
    revalidatePath("/", "layout");
    return { ok: true, id: tenant.id };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 409) {
        return {
          ok: false,
          errorCode: err.errorCode,
          message: "A tenant with that name already exists.",
        };
      }
      return { ok: false, errorCode: err.errorCode, message: err.message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}

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

/**
 * Set a tenant's cosmetic branding (accent/light colours + logo URL).
 *
 * Revalidates the whole authenticated tree on success — the runtime theme
 * (`(authenticated)/layout.tsx`) and the sidebar brand mark both read the
 * active tenant's branding, so they must re-render once colours change.
 */
export async function updateTenantBrandingAction(
  tenantId: string,
  payload: TenantBranding,
): Promise<TenantActionResult> {
  try {
    await updateTenantBranding(tenantId, payload);
    revalidatePath("/tenants");
    revalidatePath("/", "layout");
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
