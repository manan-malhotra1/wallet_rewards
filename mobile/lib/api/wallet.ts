/**
 * Wallet API calls — authenticated reads of the current user's wallet.
 *
 * The mobile home + (later) recent-activity feed both read from /me/wallet.
 * Tenant is implicit in the session token — never passed in the body.
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

export interface WalletTransaction {
  id: string;
  transaction_type: string;
  status: string;
  amount: string;
  currency: string;
  created_at: string;
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
