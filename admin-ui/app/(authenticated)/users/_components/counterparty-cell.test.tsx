/**
 * Behaviour tests for the Counterparty column of the user Transactions table.
 *
 * The motivating bug: every non-P2P row rendered "—" because the backend only
 * resolved a counterparty for `p2p`. The fix resolves any user-owned other
 * side, so these lock in what the column may and may not say — in particular
 * that it NEVER shows a service name (the Service column already carries
 * that), and that a phone equal to the name is not printed twice.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CounterpartyCell } from "@/app/(authenticated)/users/_components/counterparty-cell";
import type { UserTransaction } from "@/lib/api-endpoints";

function txn(overrides: Partial<UserTransaction> = {}): UserTransaction {
  return {
    id: "t-1",
    reference: "S_20260817180128001430",
    transaction_type: "merchant_cashin",
    status: "COMPLETED",
    amount: "1.00",
    fee_amount: "0",
    currency: "ZAR",
    created_at: "2026-08-17T23:31:00Z",
    direction: "in",
    counterparty_name: null,
    counterparty_phone: null,
    ...overrides,
  };
}

describe("CounterpartyCell", () => {
  it("shows the counterparty name with the phone beneath it", () => {
    render(
      <CounterpartyCell
        txn={txn({ counterparty_name: "Acme Airtime", counterparty_phone: "+27825550001" })}
      />,
    );
    expect(screen.getByText("Acme Airtime")).toBeInTheDocument();
    expect(screen.getByText("+27825550001")).toBeInTheDocument();
  });

  it("does not print the phone twice when it is also the resolved name", () => {
    // A user with no profile name resolves to their identifier — the phone.
    render(
      <CounterpartyCell
        txn={txn({ counterparty_name: "+27825550001", counterparty_phone: "+27825550001" })}
      />,
    );
    expect(screen.getAllByText("+27825550001")).toHaveLength(1);
  });

  it("names the system account behind a fund", () => {
    render(<CounterpartyCell txn={txn({ transaction_type: "fund" })} />);
    expect(screen.getByText("System cash inflow")).toBeInTheDocument();
  });

  it("never labels the counterparty with the service name", () => {
    // merchant_cashin has no system-account label: with nothing resolved the
    // cell must stay empty rather than echo "Merchant Cashin" / "Cash-in".
    render(<CounterpartyCell txn={txn()} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/cash.?in/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/merchant/i)).not.toBeInTheDocument();
  });
});
