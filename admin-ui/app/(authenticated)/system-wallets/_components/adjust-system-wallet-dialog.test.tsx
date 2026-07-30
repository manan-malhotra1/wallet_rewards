/**
 * Interaction tests for AdjustSystemWalletDialog from the admin operator's chair.
 *
 * The dialog lets an operator raise (Fund) or lower (Withdraw) a system
 * wallet's balance against a bank mirror. These tests exercise both directions
 * — asserting the amount is sent unsigned when funding and negative when
 * withdrawing — plus the empty-amount guard and the backend-error path. The
 * server action is mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdjustSystemWalletDialog } from "@/app/(authenticated)/system-wallets/_components/adjust-system-wallet-dialog";
import type { SystemWallet } from "@/lib/api-types";

const adjustSystemWalletAction = vi
  .fn()
  .mockResolvedValue({ ok: true, message: "Proposed." });
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  adjustSystemWalletAction: (...args: unknown[]) => adjustSystemWalletAction(...args),
}));

/** The system wallet being adjusted. */
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

/** A ZAR bank mirror (distinct from the account) for the counter-leg. */
const zarMirror: SystemWallet = {
  id: "mirror-1",
  tenant_id: "tenant-1",
  account_type: "operator_adjustment",
  currency: "ZAR",
  status: "ACTIVE",
  balance: "0",
  created_at: "2026-07-25T00:00:00Z",
  name: "Standard Bank — main float",
};

async function openDialog() {
  const user = userEvent.setup();
  render(
    <AdjustSystemWalletDialog
      account={account}
      tenantId="tenant-1"
      mirrors={[zarMirror]}
      trigger={<button type="button">Adjust</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Adjust" }));
  await screen.findByRole("dialog");
  return user;
}

async function pickMirror(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("combobox"));
  await user.click(
    await screen.findByRole("option", { name: "Standard Bank — main float" }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Adjust a system wallet", () => {
  it("Verify an admin can add float to a system wallet", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Amount (ZAR)"), "1000000");
    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Initial float wire 8023");
    await user.click(screen.getByRole("button", { name: "Fund wallet" }));

    await waitFor(() => expect(adjustSystemWalletAction).toHaveBeenCalledTimes(1));
    expect(adjustSystemWalletAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      account_id: "acct-1",
      amount: "1000000",
      reason: "Initial float wire 8023",
      bank_mirror_account_id: "mirror-1",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify an admin can draw float down from a system wallet", async () => {
    const user = await openDialog();

    // Switch the segmented control to the Withdraw direction.
    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    await user.type(screen.getByLabelText("Amount (ZAR)"), "50000");
    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Ops expense Q3");
    // Both the segmented control and the submit read "Withdraw"; the footer
    // submit is the last one in the DOM.
    const withdrawButtons = screen.getAllByRole("button", { name: "Withdraw" });
    await user.click(withdrawButtons[withdrawButtons.length - 1]);

    await waitFor(() => expect(adjustSystemWalletAction).toHaveBeenCalledTimes(1));
    expect(adjustSystemWalletAction.mock.calls[0][0]).toMatchObject({
      account_id: "acct-1",
      amount: "-50000",
      bank_mirror_account_id: "mirror-1",
    });
  });

  it("Verify an adjustment is blocked when the amount is empty", async () => {
    const user = await openDialog();

    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Initial float wire 8023");
    await user.click(screen.getByRole("button", { name: "Fund wallet" }));

    expect(
      await screen.findByText("Amount must be a positive number."),
    ).toBeInTheDocument();
    expect(adjustSystemWalletAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected adjustment shows the error to the admin", async () => {
    adjustSystemWalletAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "InsufficientFloat",
      message: "The bank mirror cannot go negative.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Amount (ZAR)"), "1000000");
    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Initial float wire 8023");
    await user.click(screen.getByRole("button", { name: "Fund wallet" }));

    expect(
      await screen.findByText(/InsufficientFloat: The bank mirror cannot go negative/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
