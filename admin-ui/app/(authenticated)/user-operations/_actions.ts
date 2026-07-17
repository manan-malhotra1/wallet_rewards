/**
 * Server actions for the User-approvals screen (Epic 3 — N-eyes maker-checker
 * for creating / editing users). Thin wrappers over the user-operation review
 * verbs; each returns the updated operation so the drawer can refresh in place,
 * and revalidates the review list + the Users page (whose data changes once an
 * operation applies).
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  approveUserOperation,
  getUserOperation,
  requestUserOpChanges,
  resubmitUserOperation,
  reviseUserOperation,
  withdrawUserOperation,
} from "@/lib/api-endpoints";
import type { UserOperation } from "@/lib/api-types";

export type UserOperationActionResult =
  | { ok: true; operation: UserOperation }
  | { ok: false; errorCode: string; message: string };

/** Surfaces whose data may change once a user operation applies. */
function revalidateAll() {
  revalidatePath("/user-operations");
  revalidatePath("/users");
}

/** Fetch a single operation with its full review thread (drawer detail). */
export async function loadUserOperationAction(
  tenantId: string,
  id: string,
): Promise<UserOperationActionResult> {
  try {
    const operation = await getUserOperation(id, tenantId);
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Approve an operation (user-approver, must differ from the maker). */
export async function approveUserOperationAction(
  tenantId: string,
  id: string,
): Promise<UserOperationActionResult> {
  try {
    const operation = await approveUserOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Ask the maker to revise, with a mandatory comment (user-approver). */
export async function requestUserOpChangesAction(
  tenantId: string,
  id: string,
  comment: string,
): Promise<UserOperationActionResult> {
  try {
    const operation = await requestUserOpChanges(tenantId, id, comment);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Revise the proposed payload and re-submit for approval in one maker action
 * (only while CHANGES_REQUESTED): PATCH the revised payload, then flip the
 * operation back to PENDING for a fresh approval round.
 */
export async function reviseAndResubmitUserOperationAction(
  tenantId: string,
  id: string,
  payload: Record<string, unknown>,
): Promise<UserOperationActionResult> {
  try {
    await reviseUserOperation(tenantId, id, payload);
    const operation = await resubmitUserOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Withdraw a non-terminal operation (maker). */
export async function withdrawUserOperationAction(
  tenantId: string,
  id: string,
): Promise<UserOperationActionResult> {
  try {
    const operation = await withdrawUserOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): UserOperationActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
