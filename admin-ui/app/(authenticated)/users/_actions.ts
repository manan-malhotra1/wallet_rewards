"use server";

/**
 * Server actions for the Users page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  addUserIdentifier,
  listUserTransactions,
  adminResetPin,
  proposeUserOperation,
  setUserAccess,
  unlockUser,
  verifyUserIdentifier,
} from "@/lib/api-endpoints";
import type { UserTransaction } from "@/lib/api-endpoints";
import type {
  AccessLevel,
  AddableIdentifierType,
  SettableAccessLevel,
} from "@/lib/api-types";

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

export type AddIdentifierActionResult =
  | { ok: true; verified: boolean }
  | { ok: false; errorCode: string; message: string };

/**
 * Epic 27, Story 27.2 — add an identifier to an existing user (platform-admin).
 * Admin-added identifiers land unverified (not OTP-proven). Revalidates /users
 * so the new row appears; surfaces a 409 duplicate with a friendly message.
 */
export async function addIdentifierAction(
  userId: string,
  tenantId: string,
  input: { identifier_type: AddableIdentifierType; identifier_value: string },
): Promise<AddIdentifierActionResult> {
  try {
    const res = await addUserIdentifier(userId, tenantId, input);
    revalidatePath("/users");
    return { ok: true, verified: res.verified };
  } catch (err) {
    if (err instanceof ApiError) {
      const message =
        err.errorCode === "identifier_already_in_use"
          ? "That identifier is already registered."
          : err.message;
      return { ok: false, errorCode: err.errorCode, message };
    }
    return {
      ok: false,
      errorCode: "internal_error",
      message: err instanceof Error ? err.message : "Unknown error",
    };
  }
}

export type VerifyIdentifierActionResult =
  | { ok: true; verified: boolean }
  | { ok: false; errorCode: string; message: string };

/**
 * Epic 27, Story 27.3 — manually mark an account_number identifier verified
 * (platform-admin). Only account numbers are verifiable this way; the backend
 * 422s `identifier_not_manually_verifiable` for phone/email (they use OTP).
 * Revalidates /users so the row flips to a Verified badge.
 */
export async function verifyIdentifierAction(
  userId: string,
  identifierId: string,
  tenantId: string,
): Promise<VerifyIdentifierActionResult> {
  try {
    const res = await verifyUserIdentifier(userId, identifierId, tenantId);
    revalidatePath("/users");
    return { ok: true, verified: res.verified };
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

/**
 * Fetch one page of a user's transactions for the detail panel.
 *
 * The panel is a client component (paging + filters are interactive), and
 * client components never call the backend directly — this action is the
 * server-side hop that carries the admin's Bearer token.
 */
export async function fetchUserTransactionsAction(
  tenantId: string,
  userId: string,
  opts: { limit?: number; offset?: number; currency?: string; q?: string },
): Promise<
  | { ok: true; items: UserTransaction[]; total: number }
  | { ok: false; errorCode: string; message: string }
> {
  try {
    const page = await listUserTransactions(tenantId, userId, opts);
    return { ok: true, items: page.items, total: page.total };
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
