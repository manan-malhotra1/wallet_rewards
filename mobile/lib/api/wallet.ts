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
  if (t.transaction_type === 'p2p') {
    const name = t.counterparty_name ?? 'Sasai user';
    return t.direction === 'in' ? `Received from ${name}` : `Sent to ${name}`;
  }
  if (t.transaction_type === 'top_up') return 'Top up';
  if (t.transaction_type === 'reward_issuance') return 'Reward earned';
  if (t.transaction_type === 'redemption') return 'Redemption';
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
  if (t.transaction_type === 'reward_issuance') return 'reward';
  if (t.transaction_type === 'redemption') return 'reward-redeem';
  if (t.transaction_type === 'top_up') return 'received';
  if (t.transaction_type === 'p2p') {
    return t.direction === 'in' ? 'received' : 'sent';
  }
  return 'generic';
}
