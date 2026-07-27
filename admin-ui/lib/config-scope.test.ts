/**
 * Tests for config scope-key derivation — the tuple that makes a config unique
 * for its type. The step_up scope is (transaction_type, currency); the point of
 * these tests is that each type keys off the right dimensions.
 */
import { describe, expect, it } from "vitest";

import { configScopeKey } from "@/lib/config-scope";

describe("Configuration identity rules", () => {
  it("A step-up policy is identified by its service and currency", () => {
    expect(
      configScopeKey("step_up", { transaction_type: "cash_in", currency: "zar" }),
    ).toBe("step_up|cash_in|ZAR");
  });

  it("Step-up policies for different services are treated as separate configs", () => {
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

  it("A tax configuration is identified by currency alone", () => {
    expect(configScopeKey("tax", { currency: "ZAR" })).toBe("tax|ZAR");
  });

  it("A wallet limit is identified by currency and customer type, defaulting to all customers when unspecified", () => {
    expect(configScopeKey("wallet_limit", { currency: "ZAR", user_type: null })).toBe(
      "wallet_limit|ZAR|all",
    );
  });

  it("A commission is identified by service, currency and customer type", () => {
    expect(
      configScopeKey("commission", {
        transaction_type: "cashout",
        currency: "ZAR",
        user_type: "agent",
      }),
    ).toBe("commission|cashout|ZAR|agent");
  });

  it("Two pricing configs count as the same only when service, account type, currency and customer type all match", () => {
    expect(
      configScopeKey("pricing", {
        transaction_type: "cash_in",
        account_type: "financial_wallet",
        currency: "ZAR",
        user_type: "all",
      }),
    ).toBe("pricing|cash_in|financial_wallet|ZAR|all");
  });

  it("A tiered pricing config takes its identity from its first tier", () => {
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
