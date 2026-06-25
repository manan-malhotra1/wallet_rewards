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
  /** Service charge debited with this transaction. "0" when none applied. */
  fee_amount: string;
  currency: 'ZAR' | 'PTS' | string;
  created_at: string;
  /** CREDIT on the user's account → "in" (money/points received). DEBIT → "out". */
  direction: TransactionDirection;
  /** P2P only: the other user's first name. Null for top-ups / rewards / redemptions. */
  counterparty_name: string | null;
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

/** Short, copy-pasteable transaction reference (first 8 chars, uppercased). */
export function transactionRef(t: WalletTransaction): string {
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
