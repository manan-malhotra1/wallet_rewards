"use server";

/**
 * Server actions for the Events page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  registerEventSource,
  type RegisterEventSourcePayload,
} from "@/lib/api-endpoints";

export type RegisterSourceResult =
  | { ok: true; sourceId: string }
  | { ok: false; errorCode: string; message: string };

export async function registerEventSourceAction(
  payload: RegisterEventSourcePayload,
): Promise<RegisterSourceResult> {
  try {
    const source = await registerEventSource(payload);
    revalidatePath("/events");
    return { ok: true, sourceId: source.id };
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
