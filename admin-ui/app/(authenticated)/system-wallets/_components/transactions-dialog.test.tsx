/**
 * Interaction tests for TransactionsDialog from the admin operator's chair.
 *
 * An operator opens the drill-down to review recent ledger activity on a
 * system wallet. History is fetched lazily on open, so these tests assert what
 * the operator sees once it resolves: populated rows, a clear empty state, or
 * an inline error when the fetch fails. The loader action is mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TransactionsDialog } from "@/app/(authenticated)/system-wallets/_components/transactions-dialog";
import type { SystemWallet, SystemWalletTransaction } from "@/lib/api-types";

const loadSystemWalletTransactionsAction = vi.fn();
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  loadSystemWalletTransactionsAction: (...args: unknown[]) =>
    loadSystemWalletTransactionsAction(...args),
}));

const account: SystemWallet = {
  id: "acct-1",
  tenant_id: "tenant-1",
  account_type: "system_cash_inflow",
  currency: "ZAR",
  status: "ACTIVE",
  balance: "0",
  created_at: "2026-07-25T00:00:00Z",
  name: null,
};

const fundRow: SystemWalletTransaction = {
  transaction_id: "txn-1",
  reference: "S_202607250001",
  transaction_type: "fund",
  status: "COMPLETED",
  entry_type: "CREDIT",
  entry_amount: "500",
  currency: "ZAR",
  created_at: "2026-07-25T10:00:00Z",
};

async function openDialog() {
  const user = userEvent.setup();
  render(
    <TransactionsDialog
      account={account}
      tenantId="tenant-1"
      trigger={<button type="button">View transactions</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "View transactions" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Review system-wallet transactions", () => {
  it("Verify an admin can review recent transactions on a system wallet", async () => {
    loadSystemWalletTransactionsAction.mockResolvedValue({ ok: true, rows: [fundRow] });
    await openDialog();

    // The row renders with a friendly type label, its reference and direction.
    expect(await screen.findByText("Fund")).toBeInTheDocument();
    expect(screen.getByText("S_202607250001")).toBeInTheDocument();
    expect(screen.getByText("CREDIT")).toBeInTheDocument();
    // The dialog asks for exactly this account's history.
    expect(loadSystemWalletTransactionsAction).toHaveBeenCalledWith("acct-1", "tenant-1");
  });

  it("Verify an admin sees a clear message when a wallet has no transactions yet", async () => {
    loadSystemWalletTransactionsAction.mockResolvedValue({ ok: true, rows: [] });
    await openDialog();

    expect(
      await screen.findByText("No transactions on this account yet."),
    ).toBeInTheDocument();
  });

  it("Verify an admin sees an error when the transaction history can't load", async () => {
    loadSystemWalletTransactionsAction.mockResolvedValue({
      ok: false,
      message: "backend_unavailable: The ledger service is unreachable.",
    });
    await openDialog();

    expect(
      await screen.findByText(/The ledger service is unreachable/),
    ).toBeInTheDocument();
  });
});
