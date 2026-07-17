/**
 * Server actions for the Money-approvals screen (Epic 18 — N-eyes
 * maker-checker for treasury moves). Thin wrappers over the money-operation
 * review verbs; each returns the updated operation so the drawer can refresh
 * in place, and revalidates the review list + the system-wallets page (whose
 * balances change once an operation applies).
 */
"use server";

import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  approveMoneyOperation,
  getMoneyOperation,
  requestMoneyOpChanges,
  resubmitMoneyOperation,
  reviseMoneyOperation,
  withdrawMoneyOperation,
} from "@/lib/api-endpoints";
import type { MoneyOperation } from "@/lib/api-types";

export type MoneyOperationActionResult =
  | { ok: true; operation: MoneyOperation }
  | { ok: false; errorCode: string; message: string };

/** Surfaces whose data may change once an operation applies. */
function revalidateAll() {
  revalidatePath("/money-operations");
  revalidatePath("/system-wallets");
}

/** Fetch a single operation with its full review thread (drawer detail). */
export async function loadMoneyOperationAction(
  tenantId: string,
  id: string,
): Promise<MoneyOperationActionResult> {
  try {
    const operation = await getMoneyOperation(id, tenantId);
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Approve an operation (treasury-approver, must differ from the maker). */
export async function approveMoneyOperationAction(
  tenantId: string,
  id: string,
): Promise<MoneyOperationActionResult> {
  try {
    const operation = await approveMoneyOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Ask the maker to revise, with a mandatory comment (treasury-approver). */
export async function requestMoneyOpChangesAction(
  tenantId: string,
  id: string,
  comment: string,
): Promise<MoneyOperationActionResult> {
  try {
    const operation = await requestMoneyOpChanges(tenantId, id, comment);
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
export async function reviseAndResubmitMoneyOperationAction(
  tenantId: string,
  id: string,
  payload: Record<string, unknown>,
): Promise<MoneyOperationActionResult> {
  try {
    await reviseMoneyOperation(tenantId, id, payload);
    const operation = await resubmitMoneyOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Withdraw a non-terminal operation (maker). */
export async function withdrawMoneyOperationAction(
  tenantId: string,
  id: string,
): Promise<MoneyOperationActionResult> {
  try {
    const operation = await withdrawMoneyOperation(tenantId, id);
    revalidateAll();
    return { ok: true, operation };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): MoneyOperationActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
