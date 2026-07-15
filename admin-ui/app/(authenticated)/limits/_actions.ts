"use server";

/**
 * Server actions for the Limits page.
 *
 * Like pricing/commission/tax, limit + wallet-limit writes now go through the
 * maker-checker pipeline: these actions PROPOSE a create/delete via
 * `POST /config-requests` (status PENDING). The change only goes live once a
 * second admin approves it in the config-requests review UI.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  proposeConfigChange,
  type CreateLimitConfigPayload,
  type CreateWalletLimitConfigPayload,
} from "@/lib/api-endpoints";

export type LimitActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/** Propose creating a service limit. Nothing goes live until a second admin approves. */
export async function proposeLimitCreateAction(
  tenantId: string,
  payload: CreateLimitConfigPayload,
): Promise<LimitActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "limit",
      operation: "create",
      payload: { ...payload },
    });
    revalidatePath("/limits");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a service limit by id. */
export async function proposeLimitDeleteAction(
  configId: string,
  tenantId: string,
): Promise<LimitActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "limit",
      operation: "delete",
      target_config_id: configId,
    });
    revalidatePath("/limits");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose creating a wallet-level limit. */
export async function proposeWalletLimitCreateAction(
  tenantId: string,
  payload: CreateWalletLimitConfigPayload,
): Promise<LimitActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "wallet_limit",
      operation: "create",
      payload: { ...payload },
    });
    revalidatePath("/limits");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Propose deleting a wallet-level limit by id. */
export async function proposeWalletLimitDeleteAction(
  configId: string,
  tenantId: string,
): Promise<LimitActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "wallet_limit",
      operation: "delete",
      target_config_id: configId,
    });
    revalidatePath("/limits");
    revalidatePath("/config-requests");
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): LimitActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
