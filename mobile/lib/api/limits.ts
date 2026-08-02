/**
 * Limits API — authenticated read of the current user's transaction limits.
 *
 * The mobile Limits screen reads from /me/limits. The backend returns one
 * entry per currency wallet, each carrying send + receive caps across three
 * rolling windows (daily / weekly / monthly). Tenant + user are implicit in
 * the session token — never passed in the body (mirrors getMyWallet).
 */
import { api } from '@/lib/api/client';

/**
 * One rolling-window axis (e.g. "daily send"): how much has been consumed
 * versus the configured cap.
 *
 * `cap_count` / `cap_value` are `null` when there is no limit on that axis —
 * the UI then shows "No limit" and only the consumed figure (no progress bar).
 * Values are Decimal strings in the wallet's currency; counts are integers.
 */
export interface LimitAxis {
  /** Number of transactions already made in the window. */
  consumed_count: number;
  /** Max transactions allowed in the window, or null for no count cap. */
  cap_count: number | null;
  /** Value already moved in the window (Decimal string, wallet currency). */
  consumed_value: string;
  /** Max value allowed in the window (Decimal string), or null for no cap. */
  cap_value: string | null;
}

/** The three rolling windows a direction (send / receive) is capped across. */
export interface LimitWindows {
  daily: LimitAxis;
  weekly: LimitAxis;
  monthly: LimitAxis;
}

/** Limits for a single currency wallet — send + receive across all windows. */
export interface MyLimits {
  /** Wallet currency code, e.g. "ZAR", "INR". */
  currency: string;
  /** Caps on money the user sends out. */
  send: LimitWindows;
  /** Caps on money the user receives. */
  receive: LimitWindows;
}

/**
 * GET /me/limits — the auth'd user's send/receive limits, one entry per
 * currency wallet.
 *
 * Returns:
 *   An array of per-currency limit blocks. Empty when the user has no wallets.
 */
export async function getMyLimits(): Promise<MyLimits[]> {
  return api<MyLimits[]>({
    path: '/api/v1/identity/me/limits',
    method: 'GET',
    withAuth: true,
  });
}
