/**
 * A checker must be able to SEE the money terms they are approving.
 *
 * The commission-wallet edition added four money-affecting fields to a
 * commission config — where it pays, and what the earner's supervisor earns —
 * but the review drawer built its band table from three keys and rendered none
 * of them. Four-eyes means the second pair of eyes can see what it is signing.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfigDetail } from "@/app/(authenticated)/_components/config-detail";

/** A commission band as the create dialog submits it. */
function band(overrides: Record<string, unknown> = {}) {
  return {
    tenant_id: "t-1",
    transaction_type: "cash_in",
    currency: "ZAR",
    user_type: "agent",
    amount_from: "1",
    amount_to: "20000",
    fixed_commission: "5",
    variable_commission_pct: "0",
    commission_cap: null,
    payout_destination: "commission_wallet",
    parent_fixed_commission: "0.5",
    parent_variable_commission_pct: "0.005",
    parent_commission_cap: null,
    ...overrides,
  };
}

function renderDetail(bands: Record<string, unknown>[]) {
  render(<ConfigDetail configType="commission" data={{ bands }} />);
}

describe("Commission approval drawer", () => {
  it("shows where the commission pays", () => {
    renderDetail([band()]);
    expect(screen.getByText("Commission wallet")).toBeInTheDocument();
    expect(screen.getByText(/held for review/i)).toBeInTheDocument();
  });

  it("shows a main-wallet rule without the held-for-review caveat", () => {
    renderDetail([band({ payout_destination: "main_wallet" })]);
    expect(screen.getByText("Main wallet")).toBeInTheDocument();
    expect(screen.queryByText(/held for review/i)).not.toBeInTheDocument();
  });

  it("shows what the supervisor earns", () => {
    renderDetail([band()]);
    expect(screen.getByText("Parent commission")).toBeInTheDocument();
    expect(screen.getByText("0.50")).toBeInTheDocument();
    expect(screen.getByText("0.50%")).toBeInTheDocument();
  });

  it("renders a zero parent rate explicitly, never as a blank", () => {
    // Stating zero is a decision the maker is REQUIRED to make (spec D8), so a
    // blank would erase the difference between "stated zero" and "not set".
    renderDetail([
      band({ parent_fixed_commission: "0", parent_variable_commission_pct: "0" }),
    ]);
    // The band's own variable rate is also 0.00% here, so both a zero amount
    // and a zero percentage are rendered — what matters is that neither is
    // blank.
    expect(screen.getAllByText("0.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.00%").length).toBeGreaterThan(0);
  });

  it("renders a legacy payload backfilled by migration 0069 as explicit zeros", () => {
    // Requests written before the parent fields existed were backfilled with
    // "0"; they must read as a stated zero, not as missing data.
    renderDetail([
      band({
        payout_destination: "main_wallet",
        parent_fixed_commission: "0",
        parent_variable_commission_pct: "0",
        parent_commission_cap: null,
      }),
    ]);
    expect(screen.getByText("Main wallet")).toBeInTheDocument();
    expect(screen.getAllByText("0.00").length).toBeGreaterThan(0);
  });

  it("warns when the terms disagree between bands", () => {
    // Scope-level in the dialog, per-row in storage — a payload that disagrees
    // must not silently show only the first band's value.
    renderDetail([band(), band({ parent_fixed_commission: "9" })]);
    expect(screen.getByText(/differ between bands/i)).toBeInTheDocument();
  });

  it("leaves a pricing config untouched", () => {
    render(
      <ConfigDetail
        configType="pricing"
        data={{
          bands: [
            {
              transaction_type: "p2p",
              currency: "ZAR",
              fixed_fee: "2",
              variable_fee_pct: "0",
              fee_cap: null,
            },
          ],
        }}
      />,
    );
    expect(screen.queryByText("Parent commission")).not.toBeInTheDocument();
    expect(screen.queryByText("Pays into")).not.toBeInTheDocument();
  });
});
