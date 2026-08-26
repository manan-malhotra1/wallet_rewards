/**
 * The commission wallet and the commission POOL must never read alike.
 *
 * They are two different accounts — the pool funds payouts, the wallet holds
 * them — and an operator reading a balance sheet has to be able to tell which
 * one they are looking at.
 */
import { describe, expect, it } from "vitest";

import { accountTypeLabel } from "@/lib/account-type-label";

describe("Commission account wording", () => {
  it("Verify a user's commission wallet is labelled 'Commission Wallet'", () => {
    expect(accountTypeLabel("commission_wallet")).toBe("Commission Wallet");
  });

  it("Verify the tenant funding pool keeps its own distinct label", () => {
    expect(accountTypeLabel("commission")).toBe("Commission Funded Wallet");
  });

  it("Verify the two labels are not the same string", () => {
    expect(accountTypeLabel("commission_wallet")).not.toBe(
      accountTypeLabel("commission"),
    );
  });
});
