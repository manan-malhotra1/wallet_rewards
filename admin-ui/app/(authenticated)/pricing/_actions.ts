"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  createPricingConfig,
  deletePricingConfig,
  type CreatePricingConfigPayload,
} from "@/lib/api-endpoints";

export type PricingActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function createPricingConfigAction(
  payload: CreatePricingConfigPayload,
): Promise<PricingActionResult> {
  try {
    await createPricingConfig(payload);
    revalidatePath("/pricing");
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

export async function deletePricingConfigAction(
  configId: string,
  tenantId: string,
): Promise<PricingActionResult> {
  try {
    await deletePricingConfig(configId, tenantId);
    revalidatePath("/pricing");
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
