"use server";

/**
 * Server actions for the System Wallets page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  adjustSystemWallet,
  createBankMirror,
  fundUser,
  listSystemWalletTransactions,
  renameBankMirror,
  withdrawFromUser,
  type AdjustSystemWalletPayload,
  type CreateBankMirrorPayload,
  type FundUserPayload,
  type WithdrawFromUserPayload,
} from "@/lib/api-endpoints";
import type { SystemWalletTransaction } from "@/lib/api-types";

export type TreasuryActionResult =
  | { ok: true; message: string }
  | { ok: false; errorCode: string; message: string };

/**
 * Epic 18: treasury moves are now maker-checker proposals, not direct posts.
 * The success toast reflects that nothing moved yet — it awaits approval.
 *
 * @param requiredApprovals N in the N-eyes rule (1 or 2) for this operation.
 */
function proposedMessage(requiredApprovals: number): string {
  const needs =
    requiredApprovals > 1
      ? `${requiredApprovals} approvals`
      : "1 approval";
  return `Proposed — pending ${needs}. Track it under Money approvals. Nothing has moved yet.`;
}

export async function fundUserAction(
  payload: FundUserPayload,
): Promise<TreasuryActionResult> {
  if (!payload.reason.trim()) {
    return { ok: false, errorCode: "missing_reason", message: "Reason is required." };
  }
  try {
    const op = await fundUser(payload);
    // Epic 18: no longer executes directly — this proposes a money operation.
    revalidatePath("/system-wallets");
    revalidatePath("/money-operations");
    return { ok: true, message: proposedMessage(op.required_approvals) };
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

export async function withdrawFromUserAction(
  payload: WithdrawFromUserPayload,
): Promise<TreasuryActionResult> {
  if (!payload.reason.trim()) {
    return { ok: false, errorCode: "missing_reason", message: "Reason is required." };
  }
  try {
    const op = await withdrawFromUser(payload);
    revalidatePath("/system-wallets");
    revalidatePath("/money-operations");
    return { ok: true, message: proposedMessage(op.required_approvals) };
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

export async function adjustSystemWalletAction(
  payload: AdjustSystemWalletPayload,
): Promise<TreasuryActionResult> {
  if (!payload.reason.trim()) {
    return { ok: false, errorCode: "missing_reason", message: "Reason is required." };
  }
  if (Number(payload.amount) === 0) {
    return { ok: false, errorCode: "amount_zero", message: "Amount must be non-zero." };
  }
  try {
    const op = await adjustSystemWallet(payload);
    revalidatePath("/system-wallets");
    revalidatePath("/money-operations");
    return { ok: true, message: proposedMessage(op.required_approvals) };
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

/** Create a new named bank-mirror (operator_adjustment) account. */
export async function createBankMirrorAction(
  tenantId: string,
  payload: CreateBankMirrorPayload,
): Promise<TreasuryActionResult> {
  if (!payload.name.trim()) {
    return { ok: false, errorCode: "missing_name", message: "Name is required." };
  }
  try {
    const op = await createBankMirror(tenantId, {
      currency: payload.currency.toUpperCase(),
      name: payload.name.trim(),
    });
    revalidatePath("/system-wallets");
    revalidatePath("/money-operations");
    return { ok: true, message: proposedMessage(op.required_approvals) };
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

/** Rename an existing bank-mirror account. */
export async function renameBankMirrorAction(
  tenantId: string,
  accountId: string,
  name: string,
): Promise<TreasuryActionResult> {
  if (!name.trim()) {
    return { ok: false, errorCode: "missing_name", message: "Name is required." };
  }
  try {
    const res = await renameBankMirror(tenantId, accountId, { name: name.trim() });
    revalidatePath("/system-wallets");
    return { ok: true, message: `Renamed to "${res.name ?? res.id}".` };
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

/** Used by the drill-down dialog; returns null on error so the UI can render an inline error. */
export async function loadSystemWalletTransactionsAction(
  accountId: string,
  tenantId: string,
): Promise<{ ok: true; rows: SystemWalletTransaction[] } | { ok: false; message: string }> {
  try {
    const rows = await listSystemWalletTransactions(accountId, tenantId);
    return { ok: true, rows };
  } catch (err) {
    if (err instanceof ApiError) {
      return { ok: false, message: `${err.errorCode}: ${err.message}` };
    }
    return {
      ok: false,
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}
