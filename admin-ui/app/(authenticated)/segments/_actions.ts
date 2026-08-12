"use server";

/**
 * Server actions for the Segments page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  addUserToSegment,
  createSegment,
  createSegmentGroup,
  deleteSegmentGroup,
  previewSegmentCriteria,
  recomputeSegments,
  type CreateSegmentGroupPayload,
  type CreateSegmentPayload,
} from "@/lib/api-endpoints";
import type { SegmentCriteriaDoc } from "@/lib/api-types";

export type SegmentActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Result of a criteria dry-run preview — the match count on success. */
export type PreviewActionResult =
  | { ok: true; count: number }
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

/**
 * Dry-run a criteria document against the tenant's current users, without
 * saving a segment. Used by the create dialog's "Preview matches" button.
 */
export async function previewCriteriaAction(
  tenantId: string,
  criteria: SegmentCriteriaDoc,
): Promise<PreviewActionResult> {
  try {
    const { match_count } = await previewSegmentCriteria(tenantId, criteria);
    return { ok: true, count: match_count };
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

/** Create a new segment group (the exclusive-tier "lens" segments belong to). */
export async function createSegmentGroupAction(
  payload: CreateSegmentGroupPayload,
): Promise<SegmentActionResult> {
  try {
    await createSegmentGroup(payload);
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

/** Delete a segment group. Backend 409s if it's system-owned or still has segments. */
export async function deleteSegmentGroupAction(
  groupId: string,
  tenantId: string,
): Promise<SegmentActionResult> {
  try {
    await deleteSegmentGroup(groupId, tenantId);
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

/** Enqueue an async recompute of every dynamic segment for the tenant. */
export async function recomputeSegmentsAction(
  tenantId: string,
): Promise<SegmentActionResult> {
  try {
    await recomputeSegments(tenantId);
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
