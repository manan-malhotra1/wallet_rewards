"use server";

/**
 * Server actions for the Redemption page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  registerProvider,
  type RegisterProviderPayload,
} from "@/lib/api-endpoints";

export type ProviderRegisterResult =
  | { ok: true; providerId: string }
  | { ok: false; errorCode: string; message: string };

export async function registerProviderAction(
  payload: RegisterProviderPayload,
): Promise<ProviderRegisterResult> {
  try {
    const provider = await registerProvider(payload);
    revalidatePath("/redemption");
    return { ok: true, providerId: provider.id };
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
