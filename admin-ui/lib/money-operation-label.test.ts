/**
 * Tests for money-operation labels and one-line summaries shown in the
 * money-approvals table. A raw operation code must never leak, and summaries
 * must tolerate odd payload shapes without throwing.
 */
import { describe, expect, it } from "vitest";

import {
  moneyOperationLabel,
  moneyOperationSummary,
} from "@/lib/money-operation-label";
import type { MoneyOperation, MoneyOperationType } from "@/lib/api-types";

/** Minimal MoneyOperation factory — only the fields the summary reads. */
function op(overrides: Partial<MoneyOperation>): MoneyOperation {
  return {
    id: "m1",
    tenant_id: "t1",
    operation: "fund_user" as MoneyOperationType,
    payload: {},
    status: "pending",
    maker_admin_id: "admin-1",
    maker_admin_name: "Alice",
    required_approvals: 2,
    approvals_count: 1,
    applied_transaction_id: null,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    subject_name: null,
    account_name: null,
    bank_mirror_name: null,
    ...overrides,
  } as MoneyOperation;
}

describe("moneyOperationLabel maps codes and falls back safely", () => {
  it("labels withdraw_user as 'Withdraw from user'", () => {
    expect(moneyOperationLabel("withdraw_user")).toBe("Withdraw from user");
  });

  it("returns the raw code for an unknown operation", () => {
    expect(moneyOperationLabel("teleport_funds")).toBe("teleport_funds");
  });
});

describe("moneyOperationSummary renders a compact one-liner", () => {
  it("summarizes fund_user with amount, currency and resolved name", () => {
    const summary = moneyOperationSummary(
      op({
        operation: "fund_user",
        payload: { amount: "150", currency: "ZAR" },
        subject_name: "Bob Jones",
      }),
    );
    expect(summary).toBe("ZAR 150.00 → Bob Jones");
  });

  it("summarizes adjust_system_wallet with a signed amount", () => {
    const summary = moneyOperationSummary(
      op({
        operation: "adjust_system_wallet",
        payload: { amount: "-50", account_id: "acc-1" },
        account_name: "Cash float",
      }),
    );
    expect(summary).toBe("−50.00 on Cash float");
  });
});
