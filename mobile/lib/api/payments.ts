/**
 * Payments API — P2P transfer (Sasai Pay redesign).
 *
 * The redesign always routes the user through a dedicated /p2p/pin
 * screen between amount entry and the actual send, so this module drops
 * the old try-then-PIN retry helper. Callers pass the PIN (always),
 * we send it once. The backend ignores PIN below step-up threshold,
 * accepts it above, and returns invalid_step_up_pin on wrong PIN —
 * the PIN screen handles the wrong-PIN retry inline.
 */
import { api, newIdempotencyKey } from '@/lib/api/client';

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
  /** Amount as a decimal string. Currency is fixed to ZAR for the demo. */
  amount: string;
  /** 4–6 digit PIN entered by the user. */
  pin: string;
  /** Optional short note carried on the txn description. */
  description?: string;
  /** Pre-generated idempotency key so the PIN screen can retry on
   *  invalid_step_up_pin without producing a different key. */
  idempotencyKey?: string;
}

/**
 * Send a P2P transfer. Always includes the PIN; the backend tolerates a
 * PIN below the step-up threshold (just ignores it) and requires it
 * above. The caller is expected to come from the /p2p/pin screen where
 * the user entered the digits.
 */
export async function sendP2P(args: P2PArgs): Promise<P2PResponse> {
  const idempotencyKey = args.idempotencyKey ?? newIdempotencyKey();
  return api<P2PResponse>({
    path: '/api/v1/payments/p2p',
    method: 'POST',
    body: {
      recipient: { identifier_type: 'phone', identifier_value: args.recipientPhone },
      amount: args.amount,
      currency: 'ZAR',
      pin: args.pin,
      ...(args.description ? { description: args.description } : {}),
    },
    withAuth: true,
    idempotencyKey,
  });
}
