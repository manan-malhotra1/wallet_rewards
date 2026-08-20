/**
 * Audit-log humanization helpers — turn raw action codes, actor types and
 * before/after JSON into plain language for the admin audit view.
 *
 * Pure string helpers only (no React), so both the table row and the detail
 * drawer can share the exact same phrasing.
 */
import type { AuditEntry } from "@/lib/api-types";

/** Friendly phrase for each known audit action code. Unknown codes are humanized. */
const ACTION_LABELS: Record<string, string> = {
  // User operations
  "user.created": "User created",
  "user.updated": "User updated",
  "user.identifier_added": "Identifier added",
  "user.role_assigned": "Role assigned",
  "user.role_removed": "Role removed",
  "user.type_changed": "User type changed",
  "admin.user_access_changed": "User access changed",
  "admin.user_unlocked": "PIN lockout cleared",
  "admin.pin_reset": "PIN reset",
  // User-initiated security
  "pin.changed": "PIN changed",
  "pin.step_up_ok": "Step-up verified",
  "pin.step_up_failed": "Step-up failed",
  // Config (maker-checker surfaces)
  "pricing_config.created": "Pricing config created",
  "pricing_config.updated": "Pricing config updated",
  "pricing_config.deleted": "Pricing config deleted",
  "limit_config.created": "Limit config created",
  "limit_config.updated": "Limit config updated",
  "limit_config.deleted": "Limit config deleted",
  "wallet_limit_config.created": "Wallet limit config created",
  "wallet_limit_config.updated": "Wallet limit config updated",
  "wallet_limit_config.deleted": "Wallet limit config deleted",
  "commission_config.created": "Commission config created",
  "commission_config.updated": "Commission config updated",
  "commission_config.deleted": "Commission config deleted",
  "tax_config.created": "Tax config created",
  "tax_config.updated": "Tax config updated",
  "tax_config.deleted": "Tax config deleted",
  "step_up_policy.created": "Step-up policy created",
  "step_up_policy.updated": "Step-up policy updated",
  "step_up_policy.deleted": "Step-up policy deleted",
  "conversion_rate_config.created": "Conversion rate created",
  "conversion_rate_config.updated": "Conversion rate updated",
  "conversion_rate_config.deleted": "Conversion rate deleted",
  "redemption.internal": "Points redeemed to wallet",
  // Money movement
  "cash_in.completed": "Cash-in completed",
  "cashout.completed": "Cash-out completed",
  "external.fund": "Wallet funded",
  "external.withdraw": "Wallet withdrawal",
  "external.merchant_cashin": "Merchant cash-in",
  "treasury.adjust_system_wallet": "System wallet adjusted",
  "treasury.fund_user": "User funded from treasury",
  "treasury.withdraw_from_user": "User debited to treasury",
  "treasury.create_bank_mirror": "Bank mirror created",
  "treasury.rename_bank_mirror": "Bank mirror renamed",
  "redemption.initiated": "Redemption initiated",
  // Ledger / accounts
  "account.created": "Account created",
  // Rules & rewards
  "rule.created": "Rule created",
  "rule.updated": "Rule updated",
  "rule.deleted": "Rule deleted",
  "multiplier.created": "Multiplier created",
  "multiplier.deleted": "Multiplier deleted",
  "segment.created": "Segment created",
  "segment.user_added": "User added to segment",
  "budget.created": "Budget created",
  "budget.deleted": "Budget deleted",
  "budget.exhausted": "Budget exhausted",
  // Platform / access
  "role.created": "Role created",
  "role.updated": "Role updated",
  "role.permission_granted": "Permission granted",
  "role.permission_revoked": "Permission revoked",
  "api_key.created": "API key created",
  "api_key.revoked": "API key revoked",
  "instrument.created": "Instrument created",
  "instrument.updated": "Instrument updated",
  "instrument.deleted": "Instrument deleted",
  "service.created": "Service created",
  "service.updated": "Service updated",
  "service.deleted": "Service deleted",
  "provider.registered": "Provider registered",
  "event_source.registered": "Event source registered",
  "tenant.updated": "Tenant updated",
};

/** Turn `a_snake.dotted_code` into a Title Cased phrase (fallback for unknown codes). */
function humanizeToken(code: string): string {
  const words = code.split(/[._]/).filter(Boolean);
  if (words.length === 0) return code;
  return words
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/** Human label for a raw user status value (e.g. `txn_locked` → "Transactions locked"). */
export function humanizeStatus(status: string): string {
  const map: Record<string, string> = {
    active: "Active",
    suspended: "Suspended",
    closed: "Closed",
    txn_locked: "Transactions locked",
    login_locked: "Login locked",
  };
  return map[status] ?? humanizeToken(status);
}

/**
 * Derive the specific access transition from an access-changed entry's
 * before/after status. Returns null when the states don't describe a
 * recognizable transition (caller falls back to the base label).
 */
function accessTransitionDetail(entry: AuditEntry): string | null {
  const from = (entry.before_state?.status as string | undefined) ?? null;
  const to = (entry.after_state?.status as string | undefined) ?? null;
  if (!to) return null;
  if (to === "txn_locked") return "Transactions locked";
  if (from === "suspended" && to === "active") return "Login access restored";
  if (from === "active" && to === "suspended") return "Login locked";
  if (from === "txn_locked" && to === "active") return "Transactions unlocked";
  if (to === "suspended") return "Login locked";
  if (to === "active") return "Access restored";
  return null;
}

/**
 * The primary WHAT phrase for an entry: the friendly action label, refined
 * with a specific transition detail where one can be derived.
 */
export function auditActionLabel(entry: AuditEntry): string {
  if (entry.action === "admin.user_access_changed") {
    return accessTransitionDetail(entry) ?? ACTION_LABELS[entry.action];
  }
  return ACTION_LABELS[entry.action] ?? humanizeToken(entry.action);
}

/** Human-readable role for an actor type (WHO). */
export function actorRoleLabel(actorType: AuditEntry["actor_type"]): string {
  if (actorType === "admin") return "Admin";
  if (actorType === "user") return "User";
  return "System";
}

/** Where the action originated (WHERE), derived from the actor type. */
export function actorLocationLabel(actorType: AuditEntry["actor_type"]): string {
  if (actorType === "admin") return "Admin portal";
  if (actorType === "user") return "Mobile app";
  return "System";
}

/** One humanized before→after change: a labelled key with old and new values. */
export interface AuditDiffLine {
  key: string;
  label: string;
  from: string;
  to: string;
}

/** Render a single JSON value for the diff, humanizing status and nullish values. */
function formatDiffValue(key: string, value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (key === "status" && typeof value === "string") return humanizeStatus(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * Diff two state snapshots into human-readable change lines — one per key whose
 * value differs. Used to replace the raw before/after JSON in the default view;
 * the raw JSON stays available behind an expander for anything unhandled.
 */
export function diffStates(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): AuditDiffLine[] {
  const keys = new Set<string>([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ]);
  const lines: AuditDiffLine[] = [];
  for (const key of keys) {
    const from = before?.[key];
    const to = after?.[key];
    if (JSON.stringify(from) === JSON.stringify(to)) continue;
    lines.push({
      key,
      label: humanizeToken(key),
      from: formatDiffValue(key, from),
      to: formatDiffValue(key, to),
    });
  }
  return lines;
}
