/**
 * Tests for the shared account-type label map. Raw ledger type keys must never
 * reach an operator's screen, while custom wallet names pass through untouched.
 */
import { describe, expect, it } from "vitest";

import { accountTypeLabel } from "@/lib/account-type-label";

describe("Account type wording", () => {
  it("Verify the operator cash float is labelled 'Cash float', never its raw key", () => {
    expect(accountTypeLabel("system_cash_inflow")).toBe("Cash float");
  });

  it("Verify a bank mirror's type key reads as 'Bank Mirror Account'", () => {
    expect(accountTypeLabel("operator_adjustment")).toBe("Bank Mirror Account");
  });

  it("Verify a custom wallet name passes through unchanged", () => {
    expect(accountTypeLabel("Steward Bank")).toBe("Steward Bank");
  });

  it("Verify an unknown future type key is shown as-is rather than hidden", () => {
    expect(accountTypeLabel("mystery_pool")).toBe("mystery_pool");
  });
});
