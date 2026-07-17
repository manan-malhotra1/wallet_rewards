"use server";

/**
 * Server actions for the Users page.
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import {
  adminResetPin,
  changeUserType,
  createUser,
  proposeUserOperation,
  type ChangeUserTypePayload,
  type CreateUserPayload,
} from "@/lib/api-endpoints";

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

export type CreateUserActionResult =
  | { ok: true; userId: string }
  | { ok: false; errorCode: string; message: string };

/**
 * Register a user (admin). Accepts one identifier (email or phone), an
 * optional profile, a user_type (default consumer), and an optional
 * hierarchy parent. Merchant profile fields arrive with Epic 17.
 */
export async function createUserAction(
  payload: CreateUserPayload,
): Promise<CreateUserActionResult> {
  try {
    const user = await createUser(payload);
    revalidatePath("/users");
    return { ok: true, userId: user.id };
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

export type ChangeTypeActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/**
 * Change a user's type (+ optional parent). `reason` is mandatory and is
 * recorded on the audit log. The backend enforces parent compatibility and
 * platform-admin role.
 */
export async function changeUserTypeAction(
  userId: string,
  tenantId: string,
  payload: ChangeUserTypePayload,
): Promise<ChangeTypeActionResult> {
  try {
    await changeUserType(userId, tenantId, payload);
    revalidatePath("/users");
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
