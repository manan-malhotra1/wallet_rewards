/**
 * Pricing API — service-agnostic fee quote.
 *
 * One call previews the service charge for ANY service (p2p, cash-in,
 * airtime, redemption, ...) by passing the service code. Mirrors the
 * backend POST /api/v1/pricing/quote — new services need no new client.
 */
import { api } from '@/lib/api/client';

/** Mirror of backend `FeeQuoteResponse` (pricing/schemas.py). */
export interface FeeQuote {
  service: string;
  amount: string;
  fee: string;
  total: string;
  currency: string;
}

/**
 * Preview the service charge for a service + amount before committing.
 * Read-only. `service` is the service code (== transaction_type), e.g. 'p2p'.
 */
export async function quoteServiceFee(
  service: string,
  amount: string,
  currency = 'ZAR',
): Promise<FeeQuote> {
  return api<FeeQuote>({
    path: '/api/v1/pricing/quote',
    method: 'POST',
    body: { service, amount, currency },
    withAuth: true,
  });
}
