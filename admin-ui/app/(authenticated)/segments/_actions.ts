"use server";

/**
 * Server actions for the Segments page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  addUserToSegment,
  createSegment,
  type CreateSegmentPayload,
} from "@/lib/api-endpoints";

export type SegmentActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

export async function createSegmentAction(
  payload: CreateSegmentPayload,
): Promise<SegmentActionResult> {
  try {
    await createSegment(payload);
    revalidatePath("/segments");
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

export async function addUserToSegmentAction(
  segmentId: string,
  tenantId: string,
  userId: string,
): Promise<SegmentActionResult> {
  try {
    await addUserToSegment(segmentId, tenantId, userId);
    revalidatePath("/segments");
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
