/**
 * Payments API — P2P transfer (Sasai Pay, with step-up support).
 *
 * Backend treats `pin` as opportunistic. We mirror that on the client:
 * call /payments/p2p WITHOUT a PIN first; below the configured step-up
 * threshold the transfer goes through immediately, above it the server
 * responds 401 `step_up_required`. The UI routes to /p2p/pin in that
 * case, where the user enters their PIN and we replay the same request
 * (same Idempotency-Key) with the PIN attached. Wrong PIN comes back
 * as 401 `invalid_step_up_pin`; the PIN screen catches that, clears
 * the pips, and lets the user try again under the same key (no double-
 * spend risk because both rejections happen pre-ledger).
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
  /** Recipient phone in E.164 (the backend resolves to a user_id). */
  recipientPhone: string;
  /** Amount as a decimal string. Currency is fixed to ZAR for the demo. */
  amount: string;
  /** PIN. Omit on the no-PIN attempt; include on the step-up retry. */
  pin?: string;
  /** Optional short note carried on the txn description. */
  description?: string;
  /** Pre-generated idempotency key — caller passes the same one across
   *  the no-PIN attempt and the step-up retry so the backend dedups. */
  idempotencyKey: string;
}

/** Generate a fresh idempotency key for a new P2P attempt. */
export const newP2PIdempotencyKey = newIdempotencyKey;

/** Send a P2P transfer. Step-up retry is owned by the caller (amount → pin). */
export async function sendP2P(args: P2PArgs): Promise<P2PResponse> {
  return api<P2PResponse>({
    path: '/api/v1/payments/p2p',
    method: 'POST',
    body: {
      recipient: { identifier_type: 'phone', identifier_value: args.recipientPhone },
      amount: args.amount,
      currency: 'ZAR',
      ...(args.pin ? { pin: args.pin } : {}),
      ...(args.description ? { description: args.description } : {}),
    },
    withAuth: true,
    idempotencyKey: args.idempotencyKey,
  });
}
