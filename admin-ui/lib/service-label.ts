/**
 * Canonical resolver for a config transaction-type (service) code → its
 * friendly display name. Shared by every config surface (tables, view drawers,
 * approval cards) so a code like `cash_in` always reads as "Cash In".
 *
 * Prefers the tenant's service `display_name` map when supplied, else falls
 * back to the shared `transactionTypeLabel` (which title-cases unknown codes).
 */
import { transactionTypeLabel } from "@/lib/transaction-type-label";

/**
 * Friendly display name for a transaction-type code.
 *
 * @param code Raw transaction-type code (e.g. `cash_in`).
 * @param serviceNames Optional `{ code: display_name }` map from the tenant's
 *   service catalog. When absent or unmapped, falls back to `transactionTypeLabel`.
 * @returns Friendly label (e.g. `Cash In`).
 */
export function serviceLabel(
  code: string,
  serviceNames?: Record<string, string>,
): string {
  return serviceNames?.[code] ?? transactionTypeLabel(code);
}
