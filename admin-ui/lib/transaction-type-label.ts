/**
 * Friendly display names for ledger transaction-type codes. Shared by every
 * surface that renders a `transaction_type` (user transaction history,
 * system-wallet transaction drill-down) so a code like `cash_in` always
 * reads as "Cash In" rather than the raw code.
 */

const TRANSACTION_TYPE_LABEL: Record<string, string> = {
  p2p: "P2P",
  fund: "Fund",
  withdraw: "Withdraw",
  redemption: "Redemption",
  airtime_recharge: "Airtime",
  cash_in: "Cash In",
  reward_issuance: "Reward",
  reversal: "Reversal",
  treasury_adjust: "Treasury adjust",
};

/**
 * Map a raw transaction-type code to its friendly display name.
 *
 * Falls back to a title-cased version of the raw code for any type not in the
 * map, so newly added types stay readable until an explicit label is added.
 *
 * @param code Raw transaction-type code (e.g. `cash_in`).
 * @returns Friendly label (e.g. `Cash In`).
 */
export function transactionTypeLabel(code: string): string {
  const known = TRANSACTION_TYPE_LABEL[code];
  if (known) return known;
  return code
    .split("_")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}
