/**
 * Deployment-mode predicates for the active tenant (B6.1).
 *
 * `business_type` decides which product surfaces a tenant gets: 'wallet' has
 * no points programme, so every rewards surface (nav sections, points account
 * types, PTS currency) must disappear for it. One predicate, used by the
 * sidebar and the config dialogs alike, so the surfaces can never disagree —
 * and the backend enforces the same rule with a 422 (`points_not_available`),
 * because a hidden dropdown is not enforcement.
 */
import type { BusinessType } from "@/lib/api-types";

/** Whether this deployment mode includes a points/rewards programme. */
export function tenantHasRewards(businessType: BusinessType): boolean {
  return businessType === "rewards" || businessType === "both";
}

/** Sidebar sections that only exist for a points programme. */
export const REWARDS_ONLY_NAV = new Set([
  "/campaigns",
  "/segments",
  "/multipliers",
  "/budgets",
  "/redemption",
]);
