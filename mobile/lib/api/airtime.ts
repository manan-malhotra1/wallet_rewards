/**
 * Airtime API — buy prepaid airtime for a mobile number (Epic 17).
 *
 * The backend recharge endpoint has a sync/async split encoded in the HTTP
 * status: 200 when the provider resolved synchronously (COMPLETED or
 * REVERSED), 202 when it is still PENDING. Our fetch wrapper only returns the
 * parsed body (it doesn't surface the status code), so we can't read 200-vs-202
 * off the response — instead we branch on the body's `status` field, which
 * carries the same information (PENDING vs terminal).
 *
 * For a synchronous feel on the buy screen, `buyAirtime` does ONE follow-up
 * poll of `GET /airtime/{id}` when the POST comes back PENDING: many providers
 * resolve within a second, so a single short-delayed re-read usually upgrades
 * PENDING to a terminal status before we ever show the user a spinner. It is a
 * single poll by design — not a loop — so a genuinely slow provider still
 * returns promptly (as PENDING with a reference the caller can display).
 */
import { api, newIdempotencyKey } from '@/lib/api/client';

/** Re-export so screens can mint a key without importing the client directly. */
export const newAirtimeIdempotencyKey = newIdempotencyKey;

/** Terminal-ish airtime status as returned by the backend. */
export type AirtimeStatus = 'PENDING' | 'COMPLETED' | 'REVERSED' | string;

/**
 * Mirror of backend `AirtimeRechargeOut` (airtime/schemas.py).
 *
 * `currency` is server-resolved (never sent by the client). `transaction_id`
 * is the ledger transaction; `provider_reference` is the upstream carrier
 * reference (present once the provider responds). `failure_reason` is set on a
 * REVERSED recharge.
 */
export interface AirtimeResult {
  id: string;
  tenant_id: string;
  user_id: string;
  msisdn: string;
  network: string;
  amount: string;
  currency: string;
  status: AirtimeStatus;
  transaction_id: string;
  provider_reference: string | null;
  failure_reason: string | null;
  completed_at: string | null;
  created_at: string;
}

interface BuyAirtimeArgs {
  /** The number to top up, in E.164 (e.g. "+27825550142"). */
  msisdn: string;
  /** Carrier network as a plain string (e.g. "MTN", "Vodacom"). */
  network: string;
  /** Amount as a decimal string (e.g. "50.00"). */
  amount: string;
  /** Wallet currency to debit (e.g. "ZAR"). The backend resolves the buyer's
   *  financial wallet in this currency; defaults to ZAR server-side if omitted. */
  currency: string;
  /**
   * Pre-generated idempotency key. The caller passes the SAME key across a
   * retry after an error so the backend dedups (a duplicate key returns the
   * original recharge rather than double-charging).
   */
  idempotencyKey: string;
}

/** Poll delay before the single follow-up status read, in milliseconds. */
const POLL_DELAY_MS = 1200;

/** Resolve after `ms` milliseconds (single-poll pacing helper). */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Fetch the current state of a recharge (poll target for PENDING recharges).
 *
 * @param id The recharge id returned by `buyAirtime`.
 * @returns The current `AirtimeResult` for the recharge.
 */
export async function getAirtimeStatus(id: string): Promise<AirtimeResult> {
  return api<AirtimeResult>({
    path: `/api/v1/airtime/${id}`,
    method: 'GET',
    withAuth: true,
  });
}

/**
 * Buy airtime, then resolve for a synchronous feel.
 *
 * Fires `POST /airtime/recharge` (body carries msisdn/network/amount/currency).
 * If the response is already terminal (COMPLETED or
 * REVERSED) it is returned as-is. If it is PENDING, we wait a short beat and
 * poll `getAirtimeStatus` exactly once, returning whatever that read gives
 * (terminal if the provider resolved in time, still PENDING otherwise).
 *
 * @param args msisdn, network, amount, and the idempotency key (reused on retry).
 * @returns The recharge — terminal when it resolved in time, else PENDING.
 * @throws ApiError subclasses on non-2xx (409 insufficient funds, 403 not
 *   permitted, 422 validation / no merchant, etc.).
 */
export async function buyAirtime(args: BuyAirtimeArgs): Promise<AirtimeResult> {
  const recharge = await api<AirtimeResult>({
    path: '/api/v1/airtime/recharge',
    method: 'POST',
    body: {
      msisdn: args.msisdn,
      network: args.network,
      amount: args.amount,
      currency: args.currency,
    },
    withAuth: true,
    idempotencyKey: args.idempotencyKey,
  });

  if (recharge.status !== 'PENDING') return recharge;

  // Single follow-up poll — give the provider a moment, then re-read once. A
  // failed poll (e.g. transient network) must not mask a successful buy, so we
  // fall back to the original PENDING result rather than throwing.
  await delay(POLL_DELAY_MS);
  try {
    return await getAirtimeStatus(recharge.id);
  } catch {
    return recharge;
  }
}
