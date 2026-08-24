"use server";

/**
 * Server actions for the User types page (spec §9).
 *
 * There is no direct write endpoint for the user-type catalog by design: every
 * mutation is PROPOSED through the config maker-checker pipeline with
 * `config_type: "user_type"`, and only lands once a second admin approves it.
 *
 * A user type is never deleted — `users.user_type` and every config row
 * reference the code as a plain string with no foreign key, so removing a row
 * would orphan them. The catalog therefore has exactly two operations: `create`
 * and `update` (relabel, re-parent, retire, reactivate).
 */
import { revalidatePath } from "next/cache";

import { ApiError } from "@/lib/api";
import { proposeConfigChange } from "@/lib/api-endpoints";

export type UserTypeActionResult =
  | { ok: true }
  | { ok: false; errorCode: string; message: string };

/**
 * The full desired state of a user type — the maker-checker payload for BOTH
 * create and update, mirroring the backend's `UserTypeCreateRequest`.
 *
 * `code` and `category_code` are immutable after creation; an update must send
 * them back unchanged or the backend refuses the proposal at approve time.
 */
export interface ProposeUserTypeInput {
  tenant_id: string;
  /** Lowercase snake_case, max 20 chars — the join key, immutable once created. */
  code: string;
  label: string;
  category_code: string;
  /** The top-level type this one hangs under, or null for a top-level type. */
  parent_type_code: string | null;
  /** Omitted on create (the backend defaults to active); set to retire/reactivate. */
  status?: "active" | "retired";
}

/** Propose creating a user type. Nothing is assignable until approved. */
export async function proposeUserTypeChangeAction(
  input: ProposeUserTypeInput,
): Promise<UserTypeActionResult> {
  try {
    await proposeConfigChange(input.tenant_id, {
      config_type: "user_type",
      operation: "create",
      payload: { ...input },
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/**
 * Propose UPDATING a live type in place — relabel, re-parent, retire or
 * reactivate. Carries the full desired row plus the `target_config_id` of the
 * row being edited; its `code` scope must not move.
 *
 * @param tenantId - Tenant whose catalog is being changed.
 * @param targetConfigId - The live `user_types` row id.
 * @param payload - The complete desired state of that row.
 */
export async function proposeUserTypeUpdateAction(
  tenantId: string,
  targetConfigId: string,
  payload: ProposeUserTypeInput,
): Promise<UserTypeActionResult> {
  try {
    await proposeConfigChange(tenantId, {
      config_type: "user_type",
      operation: "update",
      payload: { ...payload },
      target_config_id: targetConfigId,
    });
    revalidateAll();
    return { ok: true };
  } catch (err) {
    return toResult(err);
  }
}

/** Revalidate the catalog page + the approvals queue after a proposal. */
function revalidateAll() {
  revalidatePath("/user-types");
  revalidatePath("/approvals");
}

/** Normalise a thrown error into the {ok:false} result shape. */
function toResult(err: unknown): UserTypeActionResult {
  if (err instanceof ApiError) {
    return { ok: false, errorCode: err.errorCode, message: err.message };
  }
  return {
    ok: false,
    errorCode: "internal_error",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}
