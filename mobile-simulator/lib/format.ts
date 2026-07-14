/**
 * Framework-neutral display helpers shared by the server-rendered
 * <WalletPane> and its client children (<TransactionList>) plus the
 * <EventTrigger>. No "server-only" import — safe on both sides.
 */

/**
 * Format a decimal-string amount for display, with currency-aware
 * fraction digits (points have no cents; money has two).
 */
export function formatAmount(value: string, currency: string): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const fractionDigits = currency === "PTS" ? 0 : 2;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

/**
 * Human "N ago" string from an ISO timestamp, relative to now.
 * Rendered client-side so it reads relative to the viewer's clock.
 */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

// Friendly labels for transaction types. Maps the ledger's raw type to the
// name a user recognises — notably `fund` surfaces as "Fund", matching the
// `fund` entry in the services catalog (scripts/seed.py) rather than the
// internal payments transaction type. Unlisted types title-case their code.
const TXN_TYPE_LABELS: Record<string, string> = {
  fund: "Fund",
  p2p: "P2P",
  redeem: "Redemption",
  redemption: "Redemption",
  merchant_pay: "Merchant Pay",
  airtime_recharge: "Airtime",
  cash_in: "Cash In",
  withdraw: "Withdraw",
  reward_issuance: "Reward",
  reversal: "Reversal",
};

/**
 * Map a raw transaction/event type to its display label (e.g. `fund`
 * → "Fund"). Falls back to a title-cased version of the raw code.
 */
export function transactionTypeLabel(type: string): string {
  const known = TXN_TYPE_LABELS[type];
  if (known) return known;
  return type
    .replaceAll("_", " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
