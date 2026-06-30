"use server";

/**
 * Server actions for the Limits page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createLimitConfig,
  createWalletLimitConfig,
  deleteLimitConfig,
  deleteWalletLimitConfig,
  type CreateLimitConfigPayload,
  type CreateWalletLimitConfigPayload,
} from "@/lib/api-endpoints";

export type LimitActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function createLimitConfigAction(
  payload: CreateLimitConfigPayload,
): Promise<LimitActionResult> {
  try {
    await createLimitConfig(payload);
    revalidatePath("/limits");
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

export async function deleteLimitConfigAction(
  configId: string,
  tenantId: string,
): Promise<LimitActionResult> {
  try {
    await deleteLimitConfig(configId, tenantId);
    revalidatePath("/limits");
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

export async function createWalletLimitConfigAction(
  payload: CreateWalletLimitConfigPayload,
): Promise<LimitActionResult> {
  try {
    await createWalletLimitConfig(payload);
    revalidatePath("/limits");
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

export async function deleteWalletLimitConfigAction(
  configId: string,
  tenantId: string,
): Promise<LimitActionResult> {
  try {
    await deleteWalletLimitConfig(configId, tenantId);
    revalidatePath("/limits");
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
