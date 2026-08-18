/**
 * Tests for transactionTypeLabel — the Service column's display names.
 *
 * The title-case fallback is deliberate (a new backend type stays readable
 * before anyone adds a label), but it produced "Merchant Cashin" for
 * `merchant_cashin`, so the explicit entries are locked in here.
 */
import { describe, expect, it } from "vitest";

import { transactionTypeLabel } from "@/lib/transaction-type-label";

describe("transactionTypeLabel", () => {
  it("uses the explicit label for the money-movement types", () => {
    expect(transactionTypeLabel("merchant_cashin")).toBe("Merchant Cash-In");
    expect(transactionTypeLabel("cash_in")).toBe("Cash In");
    expect(transactionTypeLabel("cashout")).toBe("Cash Out");
    expect(transactionTypeLabel("p2p")).toBe("P2P");
  });

  it("title-cases an unknown type rather than showing the raw code", () => {
    expect(transactionTypeLabel("some_new_service")).toBe("Some New Service");
  });

  it("leaves an empty code alone", () => {
    expect(transactionTypeLabel("")).toBe("");
  });
});
