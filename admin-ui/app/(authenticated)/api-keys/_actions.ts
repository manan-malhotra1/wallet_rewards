"use server";

/** Server actions for the API keys page (Epic 14 S2). */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { createApiKey, revokeApiKey, type CreateApiKeyPayload } from "@/lib/api-endpoints";
import type { ApiKeyCreated } from "@/lib/api-types";

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
