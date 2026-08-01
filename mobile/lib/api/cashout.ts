/**
 * Cash-out API — subscriber sends money from their wallet TO an agent, who
 * hands over physical cash (agent-mediated withdrawal).
 *
 * Step-up mirrors the P2P pattern: call /api/v1/cashout WITHOUT a PIN first.
 * Below the tenant's step-up threshold the cash-out completes immediately;
 * above it the backend responds 401 `step_up_required`. The UI then routes to
 * a PIN screen and replays the SAME request (same Idempotency-Key) with the
 * PIN attached. A wrong PIN comes back as 401 `invalid_step_up_pin`; the PIN
 * screen catches it and retries under the same key. Both rejections happen
 * pre-ledger, so reusing the key is safe (no double-spend).
 */
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError, RateLimited } from '@/lib/api/errors';

/** Mirror of backend `CashOutResponse` (cashout/schemas.py). */
export interface CashOutResult {
  /** The double-entry transaction id. */
  transaction_id: string;
  /** Customer-facing reference for this cash-out (may be absent). */
  reference: string | null;
  /** Lifecycle state — "COMPLETED" on the happy path. */
  status: string;
  /** Principal credited to the agent. */
  amount: string;
  /** Service fee borne by the subscriber. */
  fee: string;
  /** Commission paid to the receiving agent from the pool. */
  commission: string;
  /** Total tax collected (on fee + commission). */
  tax: string;
  /** 3-letter ISO 4217 currency (uppercase). */
  currency: string;
  /** The agent who received the cash-out. */
  agent_user_id: string;
}

interface CashOutArgs {
  /** Agent phone in E.164 — the backend resolves it to an AGENT recipient. */
  agentPhone: string;
  /** Amount as a decimal string. */
  amount: string;
  /** 3-letter currency of the active wallet (e.g. "ZAR", "INR"). */
  currency: string;
  /** PIN. Omit on the no-PIN attempt; include on the step-up retry. */
  pin?: string;
  /** Pre-generated idempotency key — the caller passes the SAME one across
   *  the no-PIN attempt and the step-up retry so the backend dedups. */
  idempotencyKey: string;
}

/** Generate a fresh idempotency key for a new cash-out attempt. */
export const newCashOutIdempotencyKey = newIdempotencyKey;

/**
 * Send a cash-out to an agent. Step-up retry is owned by the caller
 * (amount → pin), exactly like the P2P flow.
 *
 * Returns the settled cash-out receipt (fee/commission/tax) on success.
 * Throws a typed ApiError on failure (404 unknown agent, 422 recipient not
 * an agent / self cash-out, 409 insufficient funds, 401 step_up_required).
 */
export async function cashOut(args: CashOutArgs): Promise<CashOutResult> {
  return api<CashOutResult>({
    path: '/api/v1/cashout',
    method: 'POST',
    body: {
      identifier_type: 'phone',
      identifier_value: args.agentPhone,
      amount: args.amount,
      currency: args.currency,
      ...(args.pin ? { pin: args.pin } : {}),
    },
    withAuth: true,
    idempotencyKey: args.idempotencyKey,
  });
}

/**
 * Map a failed cash-out to a short, friendly, PII-free message for the
 * failure screen. Shared by the amount + PIN screens so the copy stays
 * consistent. `step_up_required` / `invalid_step_up_pin` are NOT handled
 * here — those drive the PIN flow and are branched on by the caller.
 */
export function cashOutFailureReason(e: unknown): string {
  if (e instanceof RateLimited) return 'Too many attempts. Try again later.';
  if (e instanceof ApiError) {
    if (e.status === 404) return "We couldn't find that agent. Check the number and try again.";
    if (e.status === 409) return 'Your wallet doesn’t have enough for this cash-out.';
    if (e.status === 403) return "Your account isn't permitted to cash out.";
    if (e.status === 422) {
      // Backend distinguishes self cash-out / recipient-not-an-agent by message.
      return e.message || 'That number is not a valid cash-out agent.';
    }
    return e.message || 'Cash-out failed.';
  }
  return 'Cash-out failed.';
}
