/**
 * Wallet API calls — authenticated reads of the current user's wallet.
 *
 * The mobile home + transactions tab both read from /me/wallet. Tenant
 * is implicit in the session token — never passed in the body.
 */
import { api } from '@/lib/api/client';

export interface WalletAccount {
  id: string;
  account_type: string;
  currency: string;
  status: string;
  balance: string;
  reserved_balance: string;
  available_balance: string;
}

export type TransactionDirection = 'in' | 'out';

export interface WalletTransaction {
  id: string;
  transaction_type: string;
  /**
   * The BASE flow this transaction belongs to. Equals `transaction_type`
   * unless it was made on a derived service (e.g. `transaction_type:
   * "p2p_diaspora"`, `base_transaction_type: "p2p"`).
   *
   * ALWAYS compare against this — never against `transaction_type` — when
   * deciding behaviour (filters, icons, direction labels). `transaction_type`
   * is an open set: an operator can add a derived service at any time, and
   * code that equality-checks it silently stops matching.
   */
  base_transaction_type: string;
  status: string;
  /** Always positive — direction is on the `direction` field. */
  amount: string;
  /** Service charge YOU paid on this transaction. "0" unless you were charged. */
  fee_amount: string;
  /** Tax YOU paid on this transaction. "0" unless you were charged. */
  tax_amount: string;
  /** Commission YOU earned on this transaction — non-"0" only for the agent leg. */
  commission_amount: string;
  currency: 'ZAR' | 'PTS' | string;
  created_at: string;
  /** CREDIT on the user's account → "in" (money/points received). DEBIT → "out". */
  direction: TransactionDirection;
  /** P2P only: the other user's first name. Null for top-ups / rewards / redemptions. */
  counterparty_name: string | null;
  /** Real backend reference (e.g. "S_20260731190532000078"). Null on older rows. */
  reference: string | null;
}

export interface Wallet {
  user_id: string;
  tenant_id: string;
  first_name: string | null;
  accounts: WalletAccount[];
  recent_transactions: WalletTransaction[];
}

/** GET /me/wallet — returns accounts + recent transactions for the auth'd user. */
export async function getMyWallet(): Promise<Wallet> {
  return api<Wallet>({
    path: '/api/v1/identity/me/wallet',
    method: 'GET',
    withAuth: true,
  });
}

/**
 * A money service THIS user (by user_type) may initiate on mobile. The backend
 * scopes the list per user type — e.g. a consumer gets p2p / airtime_recharge /
 * cashout / redemption / change_pin, an agent gets cash_in.
 */
export interface MyService {
  /** Stable service code, e.g. "p2p", "airtime_recharge", "cash_in". */
  code: string;
  /**
   * The base service this tile derives from, or null when it IS a base
   * service. Lets the app choose an icon/behaviour by base without knowing
   * every derived code an operator might create.
   */
  base_service_code: string | null;
  /** Human label from the backend, used as a tile fallback. */
  display_name: string;
  /** Optional longer description; null when none configured. */
  description: string | null;
}

/** GET /me/services — services the auth'd user may initiate on mobile. */
export async function getMyServices(): Promise<MyService[]> {
  return api<MyService[]>({
    path: '/api/v1/identity/me/services',
    method: 'GET',
    withAuth: true,
  });
}

/**
 * Human-readable title for an activity row.
 *
 * For P2P we use the counterparty's first name plus a "Sent to" /
 * "Received from" prefix. For top-ups / rewards / redemptions where
 * there's no user counterparty we fall back to a category label.
 */
export function transactionTitle(t: WalletTransaction): string {
  // Base flow, not exact code — a derived P2P must still read as a transfer.
  if (t.base_transaction_type === 'p2p') {
    const name = t.counterparty_name ?? 'Sasai user';
    return t.direction === 'in' ? `Received from ${name}` : `Sent to ${name}`;
  }
  if (t.base_transaction_type === 'top_up') return 'Top up';
  if (t.base_transaction_type === 'reward_issuance') return 'Reward earned';
  if (t.base_transaction_type === 'redemption') return 'Redemption';
  // Fall back to the EXACT code, not the base: if an operator created a derived
  // service we have no label for, showing "cashout atm" is more honest than
  // showing "cashout" and hiding which product the user actually used.
  return t.transaction_type.replace(/_/g, ' ');
}

/**
 * Copy-pasteable transaction reference.
 *
 * Prefers the real backend reference (e.g. "S_20260731190532000078") so the
 * app shows the same ref support + statements use. Falls back to a derived
 * "SASAI-XXXXXXXX" (first 8 chars of the id) only for older rows that predate
 * the reference field, where `reference` is null/empty.
 */
export function transactionRef(t: WalletTransaction): string {
  if (t.reference && t.reference.length > 0) return t.reference;
  return `SASAI-${t.id.slice(0, 8).toUpperCase()}`;
}

/** Map a transaction to one of ActivityRow's category tints. */
export function activityCategory(
  t: WalletTransaction,
): 'received' | 'sent' | 'bill' | 'reward' | 'reward-redeem' | 'generic' {
  // Base flow, not exact code — a derived P2P must keep its sent/received
  // tint rather than falling through to the generic colour.
  if (t.base_transaction_type === 'reward_issuance') return 'reward';
  if (t.base_transaction_type === 'redemption') return 'reward-redeem';
  if (t.base_transaction_type === 'top_up') return 'received';
  if (t.base_transaction_type === 'p2p') {
    return t.direction === 'in' ? 'received' : 'sent';
  }
  return 'generic';
}
