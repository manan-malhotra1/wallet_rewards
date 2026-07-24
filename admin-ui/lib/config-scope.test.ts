/**
 * Tests for config scope-key derivation — the tuple that makes a config unique
 * for its type. The step_up scope is (transaction_type, currency); the point of
 * these tests is that each type keys off the right dimensions.
 */
import { describe, expect, it } from "vitest";

import { configScopeKey } from "@/lib/config-scope";

describe("configScopeKey builds the right tuple per config type", () => {
  it("keys step_up on (transaction_type, currency)", () => {
    expect(
      configScopeKey("step_up", { transaction_type: "cash_in", currency: "zar" }),
    ).toBe("step_up|cash_in|ZAR");
  });

  it("distinguishes two step_up policies that differ only by transaction_type", () => {
    const cashIn = configScopeKey("step_up", {
      transaction_type: "cash_in",
      currency: "ZAR",
    });
    const p2p = configScopeKey("step_up", {
      transaction_type: "p2p",
      currency: "ZAR",
    });
    expect(cashIn).not.toBe(p2p);
  });

  it("keys tax on currency alone", () => {
    expect(configScopeKey("tax", { currency: "ZAR" })).toBe("tax|ZAR");
  });

  it("keys wallet_limit on (currency, user_type) and collapses null user_type to 'all'", () => {
    expect(configScopeKey("wallet_limit", { currency: "ZAR", user_type: null })).toBe(
      "wallet_limit|ZAR|all",
    );
  });

  it("keys commission on (transaction_type, currency, user_type)", () => {
    expect(
      configScopeKey("commission", {
        transaction_type: "cashout",
        currency: "ZAR",
        user_type: "agent",
      }),
    ).toBe("commission|cashout|ZAR|agent");
  });

  it("keys pricing on the full (transaction_type, account_type, currency, user_type) tuple", () => {
    expect(
      configScopeKey("pricing", {
        transaction_type: "cash_in",
        account_type: "financial_wallet",
        currency: "ZAR",
        user_type: "all",
      }),
    ).toBe("pricing|cash_in|financial_wallet|ZAR|all");
  });

  it("reads a band config's scope from its first band", () => {
    expect(
      configScopeKey("pricing", {
        bands: [
          {
            transaction_type: "cash_in",
            account_type: "financial_wallet",
            currency: "ZAR",
            user_type: "all",
          },
        ],
      }),
    ).toBe("pricing|cash_in|financial_wallet|ZAR|all");
  });
});
