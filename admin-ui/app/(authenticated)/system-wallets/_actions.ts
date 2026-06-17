"use server";

/**
 * Server actions for the System Wallets page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  adjustSystemWallet,
  fundUser,
  listSystemWalletTransactions,
  type AdjustSystemWalletPayload,
  type FundUserPayload,
} from "@/lib/api-endpoints";
import type { SystemWalletTransaction } from "@/lib/api-types";

export type TreasuryActionResult =
  | { ok: true; message: string }
  | { ok: false; errorCode: string; message: string };

export async function fundUserAction(
  payload: FundUserPayload,
): Promise<TreasuryActionResult> {
  if (!payload.reason.trim()) {
    return { ok: false, errorCode: "missing_reason", message: "Reason is required." };
  }
  try {
    const res = await fundUser(payload);
    revalidatePath("/system-wallets");
    revalidatePath("/users");
    return {
      ok: true,
      message: `Funded ${res.currency} ${res.amount}. New balance: ${res.new_balance}.`,
    };
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
    const res = await adjustSystemWallet(payload);
    revalidatePath("/system-wallets");
    const verb = Number(res.amount) > 0 ? "Funded" : "Withdrew";
    return {
      ok: true,
      message: `${verb} ${res.currency} ${res.amount}. New balance: ${res.new_balance}.`,
    };
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
