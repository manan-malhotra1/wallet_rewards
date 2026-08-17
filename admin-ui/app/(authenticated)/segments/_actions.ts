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
  deleteSegment,
  deleteSegmentGroup,
  previewSegmentCriteria,
  recomputeSegments,
  updateSegment,
  type CreateSegmentGroupPayload,
  type CreateSegmentPayload,
  type UpdateSegmentPayload,
} from "@/lib/api-endpoints";
import type { SegmentCriteriaDoc } from "@/lib/api-types";

export type SegmentActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Result of a criteria dry-run preview — the match count on success. */
export type PreviewActionResult =
  | { ok: true; count: number }
  | { ok: false; errorCode: string; message: string };

/**
 * Map a caught error to the `{ ok: false, errorCode, message }` shape every
 * action below returns on failure — `ApiError`'s code/message pass through
 * unchanged; anything else (a thrown non-`ApiError`, e.g. a network failure)
 * collapses to a generic `internal_error` rather than leaking a raw stack
 * trace to the client. Local to this file on purpose — the segments route's
 * own copy, not a shared `lib/` util (see coding-guidelines §1's "3 = must
 * be a util" threshold: no other route's `_actions.ts` shares this exact
 * shape today, so a premature shared abstraction isn't warranted yet).
 */
function toActionError(err: unknown): { ok: false; errorCode: string; message: string } {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}

export async function createSegmentAction(
  payload: CreateSegmentPayload,
): Promise<SegmentActionResult> {
  try {
    await createSegment(payload);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
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
    return toActionError(err);
  }
}

/**
 * Update a segment's description, group, priority, and/or criteria.
 * Consumed by the Task 11 `<EditSegmentDialog>` — the caller sends only the
 * fields that actually changed (see `UpdateSegmentPayload`'s docstring).
 */
export async function updateSegmentAction(
  segmentId: string,
  tenantId: string,
  payload: UpdateSegmentPayload,
): Promise<SegmentActionResult> {
  try {
    await updateSegment(segmentId, tenantId, payload);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}

/**
 * Delete a segment. Backend 409s if it's system-protected or still bound to
 * a rule or bonus multiplier. Consumed by the per-row delete button on
 * `<GroupSection>`.
 */
export async function deleteSegmentAction(
  segmentId: string,
  tenantId: string,
): Promise<SegmentActionResult> {
  try {
    await deleteSegment(segmentId, tenantId);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
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
    return toActionError(err);
  }
}

/**
 * Create a new segment group (the exclusive-tier "lens" segments belong to).
 * Consumed by the Task 11 group-sectioned page (group management UI), not
 * by the Task 10 create-segment dialog.
 */
export async function createSegmentGroupAction(
  payload: CreateSegmentGroupPayload,
): Promise<SegmentActionResult> {
  try {
    await createSegmentGroup(payload);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}

/**
 * Delete a segment group. Backend 409s if it's system-owned or still has
 * segments. Consumed by the Task 11 group-sectioned page.
 */
export async function deleteSegmentGroupAction(
  groupId: string,
  tenantId: string,
): Promise<SegmentActionResult> {
  try {
    await deleteSegmentGroup(groupId, tenantId);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}

/**
 * Enqueue an async recompute of every dynamic segment for the tenant.
 * Consumed by the Task 11 group-sectioned page's "Recompute" action.
 */
export async function recomputeSegmentsAction(
  tenantId: string,
): Promise<SegmentActionResult> {
  try {
    await recomputeSegments(tenantId);
    revalidatePath("/segments");
    return { ok: true };
  } catch (err) {
    return toActionError(err);
  }
}
