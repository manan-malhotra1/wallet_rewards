/**
 * Card-load SIMULATOR API — dev/demo only.
 *
 * The flow shows a card top-up, but no card rails exist: the wallet is
 * credited through the partner endpoint `POST /api/v1/external/fund`
 * (API-key + HMAC auth), which draws on the tenant's cash float via the
 * standard `fund` service. No PIN/session is involved — the partner key
 * identifies the tenant and the user is resolved by phone.
 *
 * The signature is computed over the EXACT body string that goes on the
 * wire (backend verifies HMAC over raw bytes), so this module serialises
 * once and never re-stringifies.
 */
import { env } from '@/lib/env';
import { buildSasaiSignature } from '@/lib/hmac';
import { newIdempotencyKey } from '@/lib/api/client';
import { ApiError, RateLimited, toTypedError } from '@/lib/api/errors';

/** Mirror of the backend `FundUserResponse` fields this flow uses. */
export interface CardLoadResult {
  transaction_id: string;
  status: string;
  amount: string;
  currency: string;
}

interface CardLoadArgs {
  /** Logged-in user's phone — resolves the wallet on the backend. */
  phone: string;
  /** Decimal-string amount, e.g. "250.00". */
  amount: string;
  /** 3-letter wallet currency, e.g. "ZAR". */
  currency: string;
  /** Pre-generated idempotency key (stable across retries). */
  idempotencyKey: string;
}

/** Generate a fresh idempotency key for a new card-load attempt. */
export const newCardLoadIdempotencyKey = newIdempotencyKey;

/** True when the simulator's partner key is configured in the env. */
export function cardSimConfigured(): boolean {
  return Boolean(
    process.env.EXPO_PUBLIC_CARD_SIM_KEY_ID && process.env.EXPO_PUBLIC_CARD_SIM_KEY_SECRET,
  );
}

/**
 * Credit the user's wallet, presented to the user as a card top-up.
 * Throws a typed ApiError on non-2xx (404 unknown user/wallet, 409
 * insufficient float, 422 validation/limits, 401 bad key/signature).
 */
export async function loadFromCard(args: CardLoadArgs): Promise<CardLoadResult> {
  const keyId = process.env.EXPO_PUBLIC_CARD_SIM_KEY_ID ?? '';
  const secret = process.env.EXPO_PUBLIC_CARD_SIM_KEY_SECRET ?? '';

  // Serialised ONCE — this exact string is both signed and sent.
  const rawBody = JSON.stringify({
    identifier_type: 'phone',
    identifier_value: args.phone,
    amount: args.amount,
    currency: args.currency,
    reason: 'Card top-up (simulated)',
  });

  const res = await fetch(`${env.backendUrl}/api/v1/external/fund`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-Sasai-Api-Key': keyId,
      'X-Sasai-Signature': buildSasaiSignature(rawBody, secret),
      'Idempotency-Key': args.idempotencyKey,
    },
    body: rawBody,
  });

  if (!res.ok) {
    let errorCode = `http_${res.status}`;
    let message = res.statusText || 'Card load failed';
    try {
      const data = await res.json();
      if (typeof data?.error_code === 'string') errorCode = data.error_code;
      if (typeof data?.message === 'string') message = data.message;
      if (res.status === 422 && Array.isArray(data?.detail)) {
        errorCode = 'validation_error';
        message = data.detail[0]?.msg ?? message;
      }
    } catch {
      // Non-JSON body — keep defaults.
    }
    throw toTypedError(res.status, errorCode, message);
  }
  return (await res.json()) as CardLoadResult;
}

/**
 * Map a failed card load to a short, friendly message for the failure screen.
 * Never mentions the float / partner plumbing — the user sees a card story.
 */
export function cardLoadFailureReason(e: unknown): string {
  if (e instanceof RateLimited) return 'Too many attempts. Try again in a moment.';
  if (e instanceof ApiError) {
    if (e.status === 401) return 'The top-up service is unavailable right now. Try again later.';
    if (e.status === 404) return "We couldn't find a wallet for your account in this currency.";
    if (e.status === 409) return 'The top-up service is temporarily out of funds. Try again later.';
    if (e.status === 422) return e.message || 'That top-up could not be validated.';
    return e.message || 'Card load failed.';
  }
  return 'Card load failed. Check your connection and try again.';
}
