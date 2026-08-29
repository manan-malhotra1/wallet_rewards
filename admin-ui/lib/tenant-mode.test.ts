/**
 * Tests for the deployment-mode predicates.
 *
 * Small on purpose — the value is pinning that 'wallet' is the odd one out,
 * so a future business_type addition fails here instead of silently showing
 * the rewards product to a tenant that did not buy it.
 */
import { describe, expect, it } from "vitest";

import { REWARDS_ONLY_NAV, tenantHasRewards } from "@/lib/tenant-mode";

describe("tenantHasRewards", () => {
  it("Verify a wallet-only tenant has no points programme", () => {
    expect(tenantHasRewards("wallet")).toBe(false);
  });

  it("Verify rewards and both modes have one", () => {
    expect(tenantHasRewards("rewards")).toBe(true);
    expect(tenantHasRewards("both")).toBe(true);
  });
});

describe("REWARDS_ONLY_NAV", () => {
  it("Verify the rewards-only sections are exactly the five agreed", () => {
    expect([...REWARDS_ONLY_NAV].sort()).toEqual([
      "/budgets",
      "/campaigns",
      "/multipliers",
      "/redemption-rates",
      "/segments",
    ]);
  });
});
