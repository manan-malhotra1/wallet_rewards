/**
 * Friendly labels + one-line summaries for user operations (Epic 3). Shared by
 * the user-approvals table and its detail drawer so a raw operation code like
 * `update_user` always reads as "Edit user" and never leaks.
 *
 * User-type labels are NOT defined here: types are runtime data, so they come
 * from the catalog via `lib/user-type-catalog.userTypeLabel`.
 */
import type {
  UserOperation,
  UserOperationType,
  UserTypeCatalog,
} from "@/lib/api-types";
import { userTypeLabel } from "@/lib/user-type-catalog";

/** Human label for each user operation that flows through maker-checker. */
const OPERATION_LABEL: Record<UserOperationType, string> = {
  create_user: "Create user",
  update_user: "Edit user",
};

/** Friendly labels for the editable fields of an update_user operation. */
const UPDATE_FIELD_LABEL: Record<string, string> = {
  first_name: "first name",
  last_name: "last name",
  status: "status",
  user_type: "type",
};

/**
 * Friendly display name for an operation code.
 *
 * @param operation Raw operation code (e.g. `update_user`).
 * @returns Friendly label (e.g. `Edit user`); the raw code as a defensive
 *   fallback for any future operation the UI doesn't yet know.
 */
export function userOperationLabel(operation: string): string {
  return OPERATION_LABEL[operation as UserOperationType] ?? operation;
}

/** Read a payload field as a display string, tolerating missing values. */
function field(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

/** The primary contact identifier of a create_user payload (email/phone first). */
function primaryIdentifier(
  payload: Record<string, unknown>,
): { type: string; value: string } | null {
  const raw = payload.identifiers;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const idents = raw as { identifier_type?: string; identifier_value?: string }[];
  const preferred =
    idents.find((i) => i.identifier_type === "email" || i.identifier_type === "phone") ??
    idents[0];
  if (!preferred?.identifier_value) return null;
  return {
    type: preferred.identifier_type ?? "identifier",
    value: preferred.identifier_value,
  };
}

/**
 * A compact, human one-liner describing what a user operation would do —
 * shown in the table's summary column. Never throws on an odd payload shape.
 *
 * - create_user: primary identifier + the target user type.
 * - update_user: the edited user's name + which fields change.
 *
 * @param op The operation to describe.
 * @param catalog The tenant's user-type catalog, so a tenant's own type reads
 *   by name rather than by raw code.
 */
export function userOperationSummary(
  op: UserOperation,
  catalog?: UserTypeCatalog | null,
): string {
  const p = op.payload;
  switch (op.operation) {
    case "create_user": {
      const ident = primaryIdentifier(p);
      const userType = field(p, "user_type") ?? "consumer";
      const target = ident ? ident.value : "—";
      return `${target} (${userTypeLabel(catalog, userType)})`;
    }
    case "update_user": {
      const who = op.target_name ?? "user";
      const changed = Object.keys(UPDATE_FIELD_LABEL)
        .filter((key) => field(p, key) !== null)
        .map((key) => UPDATE_FIELD_LABEL[key]);
      const fields = changed.length > 0 ? changed.join(", ") : "no fields";
      return `${who} · ${fields}`;
    }
    default:
      return "—";
  }
}
