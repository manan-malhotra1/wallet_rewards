"use server";

/**
 * Server actions for the Users page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  adminResetPin,
  proposeUserOperation,
  setUserAccess,
  unlockUser,
} from "@/lib/api-endpoints";
import type { AccessLevel, SettableAccessLevel } from "@/lib/api-types";

export type PinResetActionResult =
  | { ok: true; deliveredVia: "inline" | "sms"; newPin: string | null }
  | { ok: false; errorCode: string; message: string };

/**
 * Generate a fresh random PIN for the user. The plaintext PIN comes
 * back in the response so the admin can read it back to the user
 * over a verified channel — Phase 2 will route this through the
 * notifications module for SMS delivery, at which point the response
 * will return delivered_via='sms' and newPin=null.
 */
export async function resetUserPinAction(
  userId: string,
  tenantId: string,
): Promise<PinResetActionResult> {
  try {
    const res = await adminResetPin(userId, tenantId);
    revalidatePath("/users");
    return {
      ok: true,
      deliveredVia: res.delivered_via,
      newPin: res.new_pin,
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

export type UnlockActionResult =
  | { ok: true; wasLocked: boolean }
  | { ok: false; errorCode: string; message: string };

/**
 * Release a user's PIN lockout (platform-admin). Does NOT change the PIN
 * — distinct from resetUserPinAction. Revalidates /users so the "Locked"
 * pill disappears once the lockout is cleared.
 */
export async function unlockUserAction(
  userId: string,
  tenantId: string,
): Promise<UnlockActionResult> {
  try {
    const res = await unlockUser(userId, tenantId);
    revalidatePath("/users");
    return { ok: true, wasLocked: res.was_locked };
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

export type SetAccessActionResult =
  | { ok: true; level: AccessLevel }
  | { ok: false; errorCode: string; message: string };

/**
 * Set a user's admin-imposed access level (platform-admin) — login lock,
 * transaction lock, or restore. Immediate. Revalidates /users so the
 * access-level pill and control reflect the new state. Distinct from the
 * PIN-lockout unlockUserAction.
 */
export async function setUserAccessAction(
  userId: string,
  tenantId: string,
  level: SettableAccessLevel,
): Promise<SetAccessActionResult> {
  try {
    const res = await setUserAccess(userId, tenantId, level);
    revalidatePath("/users");
    return { ok: true, level: res.level };
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

export type ProposeActionResult =
  | { ok: true; operationId: string }
  | { ok: false; errorCode: string; message: string };

/** The create_user identifier shape (subset the maker-checker schema accepts). */
export interface ProposeCreateUserInput {
  tenantId: string;
  identifiers: {
    identifier_type: "phone" | "email";
    identifier_value: string;
  }[];
  user_type: string;
  profile?: {
    first_name?: string;
    last_name?: string;
    date_of_birth?: string;
  };
}

/**
 * Epic 3 — PROPOSE a create_user operation (does NOT create the user directly).
 * Creates a PENDING user operation that applies only after N-eyes approval.
 */
export async function proposeCreateUserAction(
  input: ProposeCreateUserInput,
): Promise<ProposeActionResult> {
  const { tenantId, ...payload } = input;
  try {
    const op = await proposeUserOperation(tenantId, "create_user", payload);
    revalidatePath("/user-operations");
    return { ok: true, operationId: op.id };
  } catch (err) {
    return toProposeResult(err);
  }
}

/** The editable fields of an update_user proposal (identifiers are not here). */
export interface ProposeUpdateUserInput {
  tenantId: string;
  target_user_id: string;
  first_name?: string;
  last_name?: string;
  status?: "active" | "suspended";
  user_type?: string;
}

/**
 * Epic 3 — PROPOSE an update_user operation (does NOT edit the user directly).
 * Only changed editable fields are sent; applies after N-eyes approval.
 */
export async function proposeUpdateUserAction(
  input: ProposeUpdateUserInput,
): Promise<ProposeActionResult> {
  const { tenantId, ...payload } = input;
  try {
    const op = await proposeUserOperation(tenantId, "update_user", payload);
    revalidatePath("/user-operations");
    revalidatePath("/users");
    return { ok: true, operationId: op.id };
  } catch (err) {
    return toProposeResult(err);
  }
}

/** Normalise a thrown error into the {ok:false} propose-result shape. */
function toProposeResult(err: unknown): ProposeActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
