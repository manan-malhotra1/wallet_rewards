/**
 * Cash-in API — the AGENT funds a CUSTOMER's wallet from the agent's own
 * e-float and earns a commission (agent-mediated deposit). The mirror of
 * cash-out: there the subscriber pays an agent; here the agent pays a customer.
 *
 * Step-up mirrors the cash-out / P2P pattern: call /api/v1/cashin WITHOUT a
 * PIN first. Below the tenant's step-up threshold the cash-in completes
 * immediately; above it the backend responds 401 `step_up_required`. The UI
 * then routes to a PIN screen and replays the SAME request (same
 * Idempotency-Key) with the PIN attached. A wrong PIN comes back as 401
 * `invalid_step_up_pin`; the PIN screen catches it and retries under the same
 * key. Both rejections happen pre-ledger, so reusing the key is safe (no
 * double-spend).
 */
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError, RateLimited } from '@/lib/api/errors';

/** Mirror of backend `CashInResponse` (cashin/schemas.py). */
export interface CashInResult {
  /** The double-entry transaction id. */
  transaction_id: string;
  /** Customer-facing reference for this cash-in (may be absent). */
  reference: string | null;
  /** Lifecycle state — "COMPLETED" on the happy path. */
  status: string;
  /** Principal credited to the customer. */
  amount: string;
  /** Service fee charged (slab pricing). */
  fee: string;
  /** Commission paid to the acting agent from the pool. */
  commission: string;
  /** Total tax collected (on fee + commission). */
  tax: string;
  /** 3-letter ISO 4217 currency (uppercase). */
  currency: string;
  /** The funded customer. */
  customer_user_id: string;
}

interface CashInArgs {
  /** Customer phone in E.164 — the backend resolves it to the CUSTOMER wallet. */
  customerPhone: string;
  /** Amount as a decimal string. */
  amount: string;
  /** 3-letter currency of the agent e-float wallet to fund from (e.g. "ZAR"). */
  currency: string;
  /** PIN. Omit on the no-PIN attempt; include on the step-up retry. */
  pin?: string;
  /** Pre-generated idempotency key — the caller passes the SAME one across
   *  the no-PIN attempt and the step-up retry so the backend dedups. */
  idempotencyKey: string;
}

/** Generate a fresh idempotency key for a new cash-in attempt. */
export const newCashInIdempotencyKey = newIdempotencyKey;

/**
 * Fund a customer via cash-in. Step-up retry is owned by the caller
 * (amount → pin), exactly like the cash-out flow. The customer is named by a
 * nested `customer` identifier (phone), per the backend `CashInRequest`.
 *
 * Returns the settled cash-in receipt (fee/commission/tax) on success.
 * Throws a typed ApiError on failure (403 not permitted, 409 insufficient
 * e-float, 404 unknown customer, 422 self / validation, 401 step_up_required).
 */
export async function cashIn(args: CashInArgs): Promise<CashInResult> {
  return api<CashInResult>({
    path: '/api/v1/cashin',
    method: 'POST',
    body: {
      customer: {
        identifier_type: 'phone',
        identifier_value: args.customerPhone,
      },
      amount: args.amount,
      currency: args.currency,
      ...(args.pin ? { pin: args.pin } : {}),
    },
    withAuth: true,
    idempotencyKey: args.idempotencyKey,
  });
}

/**
 * Map a failed cash-in to a short, friendly, PII-free message for the failure
 * screen. Shared by the amount + PIN screens so the copy stays consistent.
 * `step_up_required` / `invalid_step_up_pin` are NOT handled here — those drive
 * the PIN flow and are branched on by the caller.
 */
export function cashInFailureReason(e: unknown): string {
  if (e instanceof RateLimited) return 'Too many attempts. Try again later.';
  if (e instanceof ApiError) {
    if (e.status === 404) return "We couldn't find that customer. Check the number and try again.";
    if (e.status === 409) return 'Your e-float doesn’t have enough to fund this cash-in.';
    if (e.status === 403) return "Your account isn't permitted to cash in.";
    if (e.status === 422) {
      // Backend distinguishes self cash-in / validation errors by message.
      return e.message || 'That cash-in could not be validated.';
    }
    return e.message || 'Cash-in failed.';
  }
  return 'Cash-in failed.';
}
