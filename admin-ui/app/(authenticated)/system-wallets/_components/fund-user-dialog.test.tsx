/**
 * Interaction tests for FundUserDialog from the admin operator's chair.
 *
 * These drive the real dialog the way an operator does — open it, identify the
 * customer, type an amount and reason, submit — and assert the outcome the
 * operator cares about: the treasury fund action is proposed with exactly the
 * payload they entered, an empty/invalid amount is refused before anything is
 * sent, and a backend rejection is surfaced verbatim. The server action is
 * mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FundUserDialog } from "@/app/(authenticated)/system-wallets/_components/fund-user-dialog";

const fundUserAction = vi.fn().mockResolvedValue({ ok: true, message: "Proposed." });
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  fundUserAction: (...args: unknown[]) => fundUserAction(...args),
}));

/** Open the dialog and return the configured userEvent instance. */
async function openDialog(defaultCurrency = "ZAR") {
  const user = userEvent.setup();
  render(
    <FundUserDialog
      tenantId="tenant-1"
      defaultCurrency={defaultCurrency}
      trigger={<button type="button">Fund a user</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Fund a user" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Fund a user wallet", () => {
  it("Verify an admin can top up a customer's wallet from the operator float", async () => {
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "500");
    await user.type(screen.getByLabelText("Reason (audit)"), "Refund for failed fund");
    await user.click(screen.getByRole("button", { name: "Fund user" }));

    await waitFor(() => expect(fundUserAction).toHaveBeenCalledTimes(1));
    expect(fundUserAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      identifier_type: "phone",
      identifier_value: "+27 82 555 0001",
      amount: "500",
      currency: "ZAR",
      reason: "Refund for failed fund",
    });
    // A successful proposal closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a USD tenant's fund dialog defaults to USD, not ZAR", async () => {
    const user = await openDialog("USD");

    // The currency field is seeded from the active tenant's currency.
    expect(screen.getByLabelText("Currency")).toHaveValue("USD");

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "500");
    await user.type(screen.getByLabelText("Reason (audit)"), "Refund for failed fund");
    await user.click(screen.getByRole("button", { name: "Fund user" }));

    await waitFor(() => expect(fundUserAction).toHaveBeenCalledTimes(1));
    expect(fundUserAction.mock.calls[0][0]).toMatchObject({ currency: "USD" });
  });

  it("Verify funding is blocked when the amount is empty", async () => {
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Reason (audit)"), "Refund for failed fund");
    await user.click(screen.getByRole("button", { name: "Fund user" }));

    expect(await screen.findByText("Amount must be a positive number.")).toBeInTheDocument();
    expect(fundUserAction).not.toHaveBeenCalled();
  });

  it("Verify a failed top-up shows the error to the admin", async () => {
    fundUserAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "InsufficientFloat",
      message: "Operator float is empty. Top up from the bank first.",
    });
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "500");
    await user.type(screen.getByLabelText("Reason (audit)"), "Refund for failed fund");
    await user.click(screen.getByRole("button", { name: "Fund user" }));

    expect(
      await screen.findByText(/InsufficientFloat: Operator float is empty/),
    ).toBeInTheDocument();
    // The dialog stays open so the operator can correct and retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
