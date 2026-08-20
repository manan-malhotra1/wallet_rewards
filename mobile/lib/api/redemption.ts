/**
 * Redemption API — points → wallet value (Module 11b, Pay-PRD-1200–1295).
 *
 * Used by the "pay with points" option on P2P and airtime: the user redeems
 * N points, which credits their wallet with the fiat equivalent at the
 * tenant's configured rate, and the transaction then charges the FULL amount.
 * Net effect: the recipient gets the full amount while the wallet is only out
 * (amount − discount). This composition is deliberate — it reuses the audited
 * redemption + payment paths unchanged instead of inventing a mixed-tender
 * money path.
 *
 * Only currencies with an ACTIVE rate are redeemable; the backend fails closed
 * (422 `conversion_rate_missing`) and this module surfaces that as "no rate".
 */
import { api, newIdempotencyKey } from '@/lib/api/client';

/** Mirror of backend `ConversionRateOut` (redemption/schemas.py). */
export interface ConversionRate {
  id: string;
  currency: string;
  /** "points_per_unit PTS = value_per_unit currency" (e.g. 100 PTS = 10 ZAR). */
  points_per_unit: string;
  value_per_unit: string;
  /** Anti-drain caps (Pay-PRD-1295) — null means uncapped on that axis. */
  max_points_per_txn: string | null;
  max_balance_pct_per_txn: string | null;
  status: string;
}

/** Mirror of backend `InternalRedemptionOut` — the settled points/fiat pair. */
export interface InternalRedemptionResult {
  id: string;
  points_transaction_id: string;
  payout_transaction_id: string;
  currency: string;
  points_amount: string;
  fiat_amount: string;
}

/** The tenant's ACTIVE conversion rates — only these currencies are redeemable. */
export async function getConversionRates(): Promise<ConversionRate[]> {
  return api<ConversionRate[]>({
    path: '/api/v1/redemption/conversion-rates',
    method: 'GET',
    withAuth: true,
  });
}

/**
 * Redeem points into the user's own wallet at the configured rate.
 *
 * Settles synchronously (no PENDING state). `pin` is only needed when a
 * step-up policy for ("redemption", "PTS") sets a threshold below `points`.
 *
 * @throws StepUpRequired (401) when a PIN is required and none was given.
 * @throws ApiError 422 `conversion_rate_missing` / `redemption_txn_cap_exceeded`.
 */
export async function redeemPointsToWallet(args: {
  points: string;
  currency: string;
  pin?: string;
  idempotencyKey?: string;
}): Promise<InternalRedemptionResult> {
  return api<InternalRedemptionResult>({
    path: '/api/v1/redemption/internal',
    method: 'POST',
    body: {
      points_amount: args.points,
      currency: args.currency,
      ...(args.pin ? { pin: args.pin } : {}),
    },
    withAuth: true,
    idempotencyKey: args.idempotencyKey ?? newIdempotencyKey(),
  });
}

/** Fiat value of `points` at `rate`, rounded to 2dp (mirrors the backend). */
export function pointsToFiat(points: number, rate: ConversionRate): number {
  const per = parseFloat(rate.points_per_unit);
  const value = parseFloat(rate.value_per_unit);
  if (!Number.isFinite(per) || per <= 0) return 0;
  return Math.round(((points * value) / per) * 100) / 100;
}

/** Points needed to cover `fiat` at `rate`, rounded UP to a whole point. */
export function fiatToPoints(fiat: number, rate: ConversionRate): number {
  const per = parseFloat(rate.points_per_unit);
  const value = parseFloat(rate.value_per_unit);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.ceil((fiat * per) / value);
}

/**
 * The most points this user may apply to one transaction — the tightest of
 * every bound that exists:
 *   - their points balance;
 *   - the rate's absolute per-transaction cap (Pay-PRD-1295);
 *   - the rate's %-of-balance per-transaction cap;
 *   - the points needed to cover the transaction amount (a discount can never
 *     exceed what is being paid — redeeming beyond that is a plain redemption,
 *     not a discount).
 *
 * @returns A whole number of points, never negative.
 */
export function maxRedeemablePoints(args: {
  balance: number;
  rate: ConversionRate;
  txnAmount: number;
}): number {
  const { balance, rate, txnAmount } = args;
  const bounds: number[] = [balance];
  if (rate.max_points_per_txn != null) bounds.push(parseFloat(rate.max_points_per_txn));
  if (rate.max_balance_pct_per_txn != null) {
    bounds.push((balance * parseFloat(rate.max_balance_pct_per_txn)) / 100);
  }
  if (txnAmount > 0) bounds.push(fiatToPoints(txnAmount, rate));
  const limit = Math.min(...bounds.filter((b) => Number.isFinite(b)));
  return Math.max(0, Math.floor(limit));
}
