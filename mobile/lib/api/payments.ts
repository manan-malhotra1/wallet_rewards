/**
 * Payments API — P2P transfer with built-in step-up retry.
 *
 * The backend treats `pin` as opportunistic: clients call the endpoint
 * without a PIN first; on a 401 `step_up_required` we re-call with the
 * SAME Idempotency-Key + PIN attached. Per the ledger-invariants doc the
 * first (PIN-less) call fails BEFORE any ledger row is written, so re-using
 * the key is safe.
 *
 * Wrong-PIN responses (401 `invalid_step_up_pin`) loop back to the same
 * `askForPin` hook — the keypad re-opens with an inline error, the user
 * tries again, all under the same idempotency key. The backend's own
 * lockout (5 consecutive wrong PINs) ultimately stops the loop with a
 * RateLimited error that we surface to the caller.
 */
import { api, newIdempotencyKey } from '@/lib/api/client';
import {
  ApiError,
  InvalidStepUpPin,
  StepUpRequired,
} from '@/lib/api/errors';

/** Mirror of backend `P2PResponse` (payments/schemas.py). */
export interface P2PResponse {
  transaction_id: string;
  status: string;
  amount: string;
  currency: string;
  sender_user_id: string;
  recipient_user_id: string;
  created_at: string;
  earned_points: number | null;
}

interface P2PArgs {
  /** Recipient phone in E.164 (the backend resolves it to a user_id). */
  recipientPhone: string;
  /** ZAR amount as a decimal string ("250.00"). */
  amount: string;
  /** Optional short note carried on the txn description. */
  description?: string;
}

/**
 * Asked for a PIN, possibly with a "previous attempt was wrong" hint.
 *
 * Returns `null` if the user cancels the sheet — the sendP2P caller
 * re-throws the most recent ApiError so the screen can surface it.
 */
type AskForPin = (prevError: ApiError | null) => Promise<string | null>;

/**
 * Step-up-aware P2P send.
 *
 * Returns the P2PResponse on success; throws ApiError on failure. The
 * caller drives the PIN flow by passing `askForPin`, which is invoked
 * when the server demands a PIN OR rejects a previous attempt. The same
 * Idempotency-Key is reused across all retries — the no-PIN attempt is
 * rejected pre-ledger, and wrong-PIN attempts also reject pre-ledger,
 * so replay is the correct behavior per Pay-PRD-0200.
 */
export async function sendP2P(
  args: P2PArgs,
  askForPin: AskForPin,
): Promise<P2PResponse> {
  const idempotencyKey = newIdempotencyKey();
  const baseBody = {
    recipient: { identifier_type: 'phone', identifier_value: args.recipientPhone },
    amount: args.amount,
    currency: 'ZAR',
    ...(args.description ? { description: args.description } : {}),
  };

  // Attempt 0: no PIN. Backend tells us whether step-up is needed.
  try {
    return await api<P2PResponse>({
      path: '/api/v1/payments/p2p',
      method: 'POST',
      body: baseBody,
      withAuth: true,
      idempotencyKey,
    });
  } catch (firstError) {
    if (!(firstError instanceof StepUpRequired)) throw firstError;
  }

  // Step-up retry loop. Stops on success, on user cancel, or on any
  // non-PIN error (e.g., RateLimited from backend lockout).
  let prevError: ApiError | null = null;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const pin = await askForPin(prevError);
    if (pin === null) {
      // User dismissed the sheet — surface the step-up demand.
      throw new StepUpRequired('PIN required to continue');
    }
    try {
      return await api<P2PResponse>({
        path: '/api/v1/payments/p2p',
        method: 'POST',
        body: { ...baseBody, pin },
        withAuth: true,
        idempotencyKey, // same key — pre-ledger rejects are safe to replay
      });
    } catch (e) {
      if (e instanceof InvalidStepUpPin) {
        prevError = e;
        continue; // ask again
      }
      throw e; // lockout / network / anything else surfaces
    }
  }
}
