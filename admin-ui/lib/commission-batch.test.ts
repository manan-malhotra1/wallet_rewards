/**
 * Tests for the commission batch helpers.
 *
 * The delta and the destination rule are the two that carry real consequences:
 * the delta is what a checker approves against, and the destination rule is the
 * UI half of backend decision D7.
 */
import { describe, expect, it } from "vitest";

import {
  batchStatusLabel,
  batchTotals,
  canPayToCommissionWallet,
  isTerminal,
  payoutDestinationLabel,
  rejectReasonLabel,
  rowDelta,
  rowStatusLabel,
} from "@/lib/commission-batch";

describe("Checker delta", () => {
  it("Verify the delta is the accrued balance the run leaves behind", () => {
    expect(rowDelta("1620.00", "1500.00")).toBe(120);
  });

  it("Verify paying out the full balance shows a zero delta, not a blank", () => {
    expect(rowDelta("100.000000", "100.000000")).toBe(0);
  });

  it("Verify a row with no captured balance shows no delta rather than a false zero", () => {
    expect(rowDelta(null, "100")).toBeNull();
    expect(rowDelta("100", null)).toBeNull();
  });

  it("Verify an unparseable amount yields no delta instead of NaN on screen", () => {
    expect(rowDelta("abc", "100")).toBeNull();
  });
});

describe("Commission wallet destination rule (D7)", () => {
  it("Verify an agent on a flag-on tenant may be paid to the commission wallet", () => {
    expect(canPayToCommissionWallet(true, "agent", "retail")).toBe(true);
  });

  it("Verify a merchant qualifies too — Business is eligible, not only Retail", () => {
    expect(canPayToCommissionWallet(true, "merchant", "business")).toBe(true);
  });

  it("Verify the option disappears entirely when the tenant never opted in", () => {
    expect(canPayToCommissionWallet(false, "agent", "retail")).toBe(false);
  });

  it("Verify a consumer type is refused — consumers hold no commission wallet", () => {
    expect(canPayToCommissionWallet(true, "consumer", "consumer")).toBe(false);
  });

  it("Verify the catch-all band is refused, since it could match a consumer", () => {
    expect(canPayToCommissionWallet(true, null, "retail")).toBe(false);
  });

  it("Verify an unresolved category is refused rather than assumed eligible", () => {
    expect(canPayToCommissionWallet(true, "mystery", undefined)).toBe(false);
  });
});

describe("Reject reason wording", () => {
  it("Verify an over-payment reads as an accrual problem, not a wallet problem", () => {
    expect(rejectReasonLabel("insufficient_commission_balance")).toBe(
      "Amount is more than the accrued commission",
    );
  });

  it("Verify a duplicate line tells the maker where to look", () => {
    expect(rejectReasonLabel("duplicate_row")).toBe(
      "This mobile number and currency appear earlier in the file",
    );
  });

  it("Verify an unknown future code is shown raw rather than swallowed", () => {
    expect(rejectReasonLabel("some_new_code")).toBe("some_new_code");
  });

  it("Verify a row with no failure reason renders nothing", () => {
    expect(rejectReasonLabel(null)).toBe("");
    expect(rejectReasonLabel(undefined)).toBe("");
  });
});

describe("Status wording", () => {
  it("Verify a partially applied batch says so, rather than reading as success", () => {
    expect(batchStatusLabel("APPLIED_PARTIAL")).toBe("Applied with errors");
  });

  it("Verify a pending batch reads as awaiting approval", () => {
    expect(batchStatusLabel("PENDING")).toBe("Awaiting approval");
  });

  it("Verify a row that failed at apply is distinguished from one rejected at upload", () => {
    expect(rowStatusLabel("failed")).toBe("Failed at apply");
    expect(rowStatusLabel("rejected")).toBe("Rejected at upload");
  });

  it("Verify an unknown status is shown as-is", () => {
    expect(batchStatusLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});

describe("Terminal states", () => {
  it("Verify a rejected batch is terminal — the maker re-uploads (D16)", () => {
    expect(isTerminal("REJECTED")).toBe(true);
  });

  it("Verify a pending batch is still actionable", () => {
    expect(isTerminal("PENDING")).toBe(false);
  });

  it("Verify both applied states are terminal", () => {
    expect(isTerminal("APPLIED")).toBe(true);
    expect(isTerminal("APPLIED_PARTIAL")).toBe(true);
  });
});

describe("Destination wording", () => {
  it("Verify the two destinations read plainly", () => {
    expect(payoutDestinationLabel("commission_wallet")).toBe("Commission wallet");
    expect(payoutDestinationLabel("main_wallet")).toBe("Main wallet");
  });
});

describe("Batch totals", () => {
  const rows = [
    { status: "valid", amount: "1500.00", balance_snapshot: "1620.00" },
    { status: "valid", amount: "200.00", balance_snapshot: "200.00" },
    { status: "rejected", amount: "0", balance_snapshot: null },
  ];

  it("Verify rejected rows are excluded from the payable count and total", () => {
    const totals = batchTotals(rows);
    expect(totals.rows).toBe(3);
    expect(totals.payable).toBe(2);
    expect(totals.amount).toBe(1700);
  });

  it("Verify held-back money is summed so the checker sees it at a glance", () => {
    expect(batchTotals(rows).heldBack).toBe(120);
  });

  it("Verify an all-rejected file totals to nothing payable", () => {
    const totals = batchTotals([
      { status: "rejected", amount: "0", balance_snapshot: null },
    ]);
    expect(totals.payable).toBe(0);
    expect(totals.amount).toBe(0);
  });
});
