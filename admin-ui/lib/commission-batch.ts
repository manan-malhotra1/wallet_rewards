/**
 * Pure helpers for the commission disbursement / withdrawal screens.
 *
 * Kept DOM-free so they carry the `lib/` coverage gate and can be reasoned
 * about without rendering: the checker's delta, the status and reject-reason
 * wording, and the rule deciding whether a commission-wallet payout
 * destination may even be offered.
 */

/** Batch lifecycle status → operator-facing label. */
export const BATCH_STATUS_LABEL: Record<string, string> = {
  PENDING: "Awaiting approval",
  APPLIED: "Applied",
  APPLIED_PARTIAL: "Applied with errors",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
};

/** Per-row status → operator-facing label. */
export const ROW_STATUS_LABEL: Record<string, string> = {
  valid: "Ready",
  rejected: "Rejected at upload",
  posted: "Paid",
  failed: "Failed at apply",
};

/**
 * Machine failure reason → a sentence telling the maker what to fix.
 *
 * These are the exact codes the backend writes to
 * `commission_batch_rows.failure_reason`; the rejects CSV carries them too, so
 * the wording here and the file the operator downloads must agree.
 */
export const REJECT_REASON_LABEL: Record<string, string> = {
  msisdn_not_found: "No user with this mobile number in this tenant",
  user_not_eligible: "This user type does not hold a commission wallet",
  unknown_currency: "Not an active currency for this tenant",
  commission_wallet_missing: "This user has no commission wallet in this currency",
  invalid_amount: "Amount must be a number greater than zero",
  insufficient_commission_balance: "Amount is more than the accrued commission",
  duplicate_row: "This mobile number and currency appear earlier in the file",
  main_wallet_missing: "This user has no main wallet in this currency",
};

/** Human sentence for a failure code; unknown codes pass through unchanged. */
export function rejectReasonLabel(code: string | null | undefined): string {
  if (!code) return "";
  return REJECT_REASON_LABEL[code] ?? code;
}

/** Operator label for a batch status; unknown statuses pass through. */
export function batchStatusLabel(status: string): string {
  return BATCH_STATUS_LABEL[status] ?? status;
}

/** Operator label for a row status; unknown statuses pass through. */
export function rowStatusLabel(status: string): string {
  return ROW_STATUS_LABEL[status] ?? status;
}

/** A batch that can no longer be actioned. Rejection is terminal by design. */
export function isTerminal(status: string): boolean {
  return ["APPLIED", "APPLIED_PARTIAL", "REJECTED", "WITHDRAWN"].includes(status);
}

/**
 * How much accrued commission a row is NOT moving.
 *
 * This is the number the checker is actually evaluating: a non-zero delta means
 * the maker is holding some of the balance back, and their note must say why.
 * Returns null when no balance was captured (a row rejected before resolution),
 * so the UI can render a dash rather than a misleading zero.
 *
 * Amounts arrive as decimal strings to avoid float drift on money.
 */
export function rowDelta(
  balanceSnapshot: string | null | undefined,
  amount: string | null | undefined,
): number | null {
  if (balanceSnapshot == null || amount == null) return null;
  const balance = Number(balanceSnapshot);
  const paid = Number(amount);
  if (Number.isNaN(balance) || Number.isNaN(paid)) return null;
  return balance - paid;
}

/**
 * May this rule offer "Commission wallet" as the payout destination?
 *
 * Mirrors backend decision D7 exactly. The option is ABSENT rather than
 * disabled when this is false: a disabled control invites the operator to hunt
 * for a way to enable it, whereas an absent one says the combination does not
 * exist. The server enforces the same rule, so this is convenience, not
 * security.
 *
 * @param tenantCommissionWalletEnabled Tenant flag, chosen at tenant creation.
 * @param userTypeCode The rule's scope. `null` is the catch-all band, which
 *   could match a consumer and is therefore never eligible.
 * @param categoryCode The category that type belongs to.
 */
export function canPayToCommissionWallet(
  tenantCommissionWalletEnabled: boolean,
  userTypeCode: string | null,
  categoryCode: string | null | undefined,
): boolean {
  if (!tenantCommissionWalletEnabled) return false;
  if (userTypeCode === null) return false;
  return categoryCode === "retail" || categoryCode === "business";
}

/** Payout destination → operator label. */
export function payoutDestinationLabel(destination: string): string {
  return destination === "commission_wallet" ? "Commission wallet" : "Main wallet";
}

/** Totals for the checker's summary strip. */
export interface BatchTotals {
  rows: number;
  payable: number;
  amount: number;
  heldBack: number;
}

/**
 * Summarise a batch's rows for the header strip.
 *
 * `heldBack` sums the positive deltas only — money the maker chose to leave in
 * the commission wallets. A negative delta cannot occur (validation rejects an
 * amount above the balance), but guarding keeps the total honest if it ever did.
 */
export function batchTotals(
  rows: { status: string; amount: string; balance_snapshot: string | null }[],
): BatchTotals {
  let payable = 0;
  let amount = 0;
  let heldBack = 0;

  for (const row of rows) {
    if (row.status === "rejected") continue;
    payable += 1;
    amount += Number(row.amount) || 0;
    const delta = rowDelta(row.balance_snapshot, row.amount);
    if (delta != null && delta > 0) heldBack += delta;
  }

  return { rows: rows.length, payable, amount, heldBack };
}
