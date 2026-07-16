/**
 * Scope-grouping helpers for the pricing + commission tables (Epic 25 Pass 1).
 *
 * The backend list endpoints return flat band rows (one row per amount band).
 * A config is really one SCOPE with a sequence of bands, so the tables show
 * one row per scope. These helpers fold the flat rows into scope groups whose
 * bands are sorted by `amount_from` (nulls last), preserving a stable group
 * key for React and for the group's actions (View / Edit / Delete).
 */
import type {
  CommissionConfig,
  CommissionConfigGroup,
  PricingConfig,
  PricingConfigGroup,
} from "@/lib/api-types";

/** Compare two band rows by `amount_from`, sorting null (unbounded) last. */
function byAmountFrom(
  a: { amount_from: string | null },
  b: { amount_from: string | null },
): number {
  if (a.amount_from === null && b.amount_from === null) return 0;
  if (a.amount_from === null) return 1;
  if (b.amount_from === null) return -1;
  return parseFloat(a.amount_from) - parseFloat(b.amount_from);
}

/**
 * Group flat pricing rows into one config per scope.
 *
 * Scope = (transaction_type, account_type, currency, user_type). Groups keep
 * insertion order of first appearance; each group's bands are sorted ascending
 * by `amount_from` with unbounded (null) bands last.
 *
 * @param configs Flat pricing band rows from `listPricingConfigs`.
 * @returns One `PricingConfigGroup` per distinct scope.
 */
export function groupPricingConfigs(
  configs: PricingConfig[],
): PricingConfigGroup[] {
  const groups = new Map<string, PricingConfigGroup>();
  for (const cfg of configs) {
    const userType = cfg.user_type ?? "all";
    const key = `${cfg.transaction_type}|${cfg.account_type}|${cfg.currency}|${userType}`;
    const existing = groups.get(key);
    if (existing) {
      existing.bands.push(cfg);
    } else {
      groups.set(key, {
        key,
        transaction_type: cfg.transaction_type,
        account_type: cfg.account_type,
        currency: cfg.currency,
        user_type: cfg.user_type,
        // Scope-level fee-inclusive is shared across bands; take it from the
        // first row seen (the create dialog writes it identically per band).
        fee_inclusive: cfg.fee_inclusive,
        bands: [cfg],
      });
    }
  }
  for (const group of groups.values()) group.bands.sort(byAmountFrom);
  return [...groups.values()];
}

/**
 * Group flat commission rows into one config per scope.
 *
 * Scope = (transaction_type, currency, user_type). Same ordering guarantees as
 * {@link groupPricingConfigs}.
 *
 * @param configs Flat commission band rows from `listCommissionConfigs`.
 * @returns One `CommissionConfigGroup` per distinct scope.
 */
export function groupCommissionConfigs(
  configs: CommissionConfig[],
): CommissionConfigGroup[] {
  const groups = new Map<string, CommissionConfigGroup>();
  for (const cfg of configs) {
    const userType = cfg.user_type ?? "all";
    const key = `${cfg.transaction_type}|${cfg.currency}|${userType}`;
    const existing = groups.get(key);
    if (existing) {
      existing.bands.push(cfg);
    } else {
      groups.set(key, {
        key,
        transaction_type: cfg.transaction_type,
        currency: cfg.currency,
        user_type: cfg.user_type,
        bands: [cfg],
      });
    }
  }
  for (const group of groups.values()) group.bands.sort(byAmountFrom);
  return [...groups.values()];
}
