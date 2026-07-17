"use server";

/** Server actions for the API keys page (Epic 14 S2). */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createApiKey,
  getUserDetail,
  resolveIdentifier,
  revokeApiKey,
  type CreateApiKeyPayload,
} from "@/lib/api-endpoints";
import type { ApiKeyCreated, UserType } from "@/lib/api-types";

export type CreateApiKeyResult =
  | { ok: true; key: ApiKeyCreated }
  | { ok: false; errorCode: string; message: string };

export async function createApiKeyAction(
  payload: CreateApiKeyPayload,
): Promise<CreateApiKeyResult> {
  try {
    const key = await createApiKey(payload);
    revalidatePath("/api-keys");
    return { ok: true, key };
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

export type ResolveMerchantResult =
  | { ok: true; user_id: string; name: string | null; user_type: UserType }
  | { ok: false; errorCode: string; message: string };

/**
 * Resolve a registered identifier to a user and return its display name +
 * user_type, so the create-key dialog can confirm the merchant before binding.
 *
 * Wires two admin endpoints: `resolveIdentifier` (identifier → user_id) then
 * `getUserDetail` (user_id → profile name + user_type). A missing identifier
 * surfaces as ApiError (404) — the caller renders it inline. This does NOT
 * enforce that the user is a merchant; the dialog warns and the backend
 * re-validates on create (422 merchant_user_required).
 */
export async function resolveMerchantAction(
  tenantId: string,
  identifierType: string,
  identifierValue: string,
): Promise<ResolveMerchantResult> {
  try {
    const resolved = await resolveIdentifier(tenantId, identifierType, identifierValue);
    const detail = await getUserDetail(tenantId, resolved.user_id);
    const name = [detail.profile?.first_name, detail.profile?.last_name]
      .filter(Boolean)
      .join(" ");
    return {
      ok: true,
      user_id: detail.id,
      name: name || null,
      user_type: detail.user_type,
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

export type RevokeApiKeyResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function revokeApiKeyAction(
  keyPk: string,
  tenantId: string,
): Promise<RevokeApiKeyResult> {
  try {
    await revokeApiKey(keyPk, tenantId);
    revalidatePath("/api-keys");
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
