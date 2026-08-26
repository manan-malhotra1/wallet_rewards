/**
 * Server actions shared by the Commission Disbursement and Commission
 * Withdrawal menus (spec 2026-08-26 §8, §11).
 *
 * The two menus are the same maker-checker flow with different postings and
 * different wording, so the actions are written once here and both routes
 * import them — per the repo DRY rule, three repetitions would demand a util
 * and this is already two.
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError, apiGetText, apiPost, apiPostForm } from "@/lib/api";
import type { CommissionBatch } from "@/lib/api-types";

export type BatchActionResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; errorCode: string; message: string };

/** Map any thrown error into the discriminated result the forms render. */
function toResult(err: unknown): { ok: false; errorCode: string; message: string } {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "unexpected_error",
    message: "Something went wrong. Please try again.",
  };
}

/** Revalidate both menus — a batch list is cached per route. */
function revalidateBoth(): void {
  revalidatePath("/commission-disbursement");
  revalidatePath("/commission-withdrawal");
}

/**
 * Upload a CSV and stage a batch (maker).
 *
 * Returns the staged batch so the caller can show the validation summary —
 * how many rows will actually pay — before anyone approves anything.
 */
export async function uploadCommissionBatchAction(
  tenantId: string,
  formData: FormData,
): Promise<BatchActionResult<CommissionBatch>> {
  try {
    const batch = await apiPostForm<CommissionBatch>(
      "/api/v1/commission-batches",
      formData,
      { query: { tenant_id: tenantId } },
    );
    revalidateBoth();
    return { ok: true, data: batch };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Approve a batch (checker). Applies once the tenant's quorum is reached; the
 * returned status distinguishes APPLIED from APPLIED_PARTIAL.
 */
export async function approveCommissionBatchAction(
  tenantId: string,
  batchId: string,
): Promise<BatchActionResult<CommissionBatch>> {
  try {
    const batch = await apiPost<CommissionBatch>(
      `/api/v1/commission-batches/${batchId}/approve`,
      undefined,
      { query: { tenant_id: tenantId } },
    );
    revalidateBoth();
    return { ok: true, data: batch };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Reject the WHOLE batch with a mandatory comment (checker).
 *
 * Terminal by design: the maker corrects the file and uploads a NEW batch
 * rather than revising this one in place.
 */
export async function rejectCommissionBatchAction(
  tenantId: string,
  batchId: string,
  comment: string,
): Promise<BatchActionResult<CommissionBatch>> {
  try {
    const batch = await apiPost<CommissionBatch>(
      `/api/v1/commission-batches/${batchId}/reject`,
      { comment },
      { query: { tenant_id: tenantId } },
    );
    revalidateBoth();
    return { ok: true, data: batch };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Fetch the rejects CSV as text so the browser can offer it as a download.
 *
 * Returned as a string rather than streamed because a rejects file is bounded
 * by the batch row cap and the maker needs it in one piece to fix and re-upload.
 */
export async function fetchCommissionBatchRejectsAction(
  tenantId: string,
  batchId: string,
): Promise<BatchActionResult<string>> {
  try {
    const csv = await apiGetText(
      `/api/v1/commission-batches/${batchId}/rejects`,
      { tenant_id: tenantId },
    );
    return { ok: true, data: csv };
  } catch (err) {
    return toResult(err);
  }
}
