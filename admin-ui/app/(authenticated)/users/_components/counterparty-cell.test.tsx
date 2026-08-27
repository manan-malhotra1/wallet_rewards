/**
 * Behaviour tests for the Counterparty column of the user Transactions table.
 *
 * The column has regressed to "—" twice. First because the backend resolved a
 * counterparty only for `p2p`; then because the frontend patch for that was a
 * per-transaction-type label map, so any type nobody remembered to add — the
 * commission types — fell straight back to an empty cell.
 *
 * The label is now derived in the BACKEND from the account on the other leg,
 * which is why this component no longer carries a map. These tests cover what
 * the cell does with what it is given: it never shows a service name (the
 * Service column already carries that), and never prints a phone twice.
 * That every transaction actually GETS a counterparty is asserted where it is
 * now decided — backend/tests/identity/test_transaction_counterparty.py.
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

  it("renders a system account label supplied by the backend", () => {
    // The backend names the other leg by what the account IS when it has no
    // owning user, so the cell just renders it.
    render(
      <CounterpartyCell
        txn={txn({ transaction_type: "commission_withdrawal", counterparty_name: "Bank mirror · Primary" })}
      />,
    );
    expect(screen.getByText("Bank mirror · Primary")).toBeInTheDocument();
  });

  it("renders the other wallet for a movement between the user's own accounts", () => {
    render(
      <CounterpartyCell
        txn={txn({ transaction_type: "commission_disbursement", counterparty_name: "Commission wallet" })}
      />,
    );
    expect(screen.getByText("Commission wallet")).toBeInTheDocument();
  });

  it("never labels the counterparty with the service name", () => {
    // With nothing resolved the cell must stay empty rather than echo
    // "Merchant Cashin" / "Cash-in". The backend now always supplies a label,
    // so this is the last-resort guard, not the normal path.
    render(<CounterpartyCell txn={txn()} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/cash.?in/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/merchant/i)).not.toBeInTheDocument();
  });
});
