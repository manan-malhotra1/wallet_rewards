/**
 * Interaction tests for WithdrawFromUserDialog from the admin operator's chair.
 *
 * An operator pulls funds back out of a customer wallet, choosing which bank
 * mirror receives the counter-leg. These tests drive that flow end to end and
 * assert the outcome: the withdraw action is proposed with the entered payload
 * including the chosen mirror, submitting without a mirror is refused, and a
 * backend rejection is shown to the operator. The server action is mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WithdrawFromUserDialog } from "@/app/(authenticated)/system-wallets/_components/withdraw-from-user-dialog";
import type { SystemWallet } from "@/lib/api-types";

const withdrawFromUserAction = vi
  .fn()
  .mockResolvedValue({ ok: true, message: "Proposed." });
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  withdrawFromUserAction: (...args: unknown[]) => withdrawFromUserAction(...args),
}));

/** A ZAR bank mirror the operator can pick as the counter-leg. */
const zarMirror: SystemWallet = {
  id: "mirror-zar-1",
  tenant_id: "tenant-1",
  account_type: "operator_adjustment",
  currency: "ZAR",
  status: "ACTIVE",
  balance: "0",
  created_at: "2026-07-25T00:00:00Z",
  name: "Standard Bank — main float",
};

/** A USD bank mirror for a USD-currency tenant (e.g. Sasai-ZW). */
const usdMirror: SystemWallet = {
  ...zarMirror,
  id: "mirror-usd-1",
  currency: "USD",
  name: "Chase — USD settlement",
};

async function openDialog(
  defaultCurrency = "ZAR",
  mirrors: SystemWallet[] = [zarMirror],
) {
  const user = userEvent.setup();
  render(
    <WithdrawFromUserDialog
      tenantId="tenant-1"
      defaultCurrency={defaultCurrency}
      mirrors={mirrors}
      trigger={<button type="button">Withdraw from user</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Withdraw from user" }));
  await screen.findByRole("dialog");
  return user;
}

/** Pick the bank-mirror counter-leg (the second combobox in the dialog). */
async function pickMirror(user: ReturnType<typeof userEvent.setup>) {
  const mirrorSelect = screen.getAllByRole("combobox")[1];
  await user.click(mirrorSelect);
  await user.click(
    await screen.findByRole("option", { name: "Standard Bank — main float" }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Withdraw from a user wallet", () => {
  it("Verify an admin can pull funds back from a customer into a bank mirror", async () => {
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "200");
    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Cash-out at agent counter");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() => expect(withdrawFromUserAction).toHaveBeenCalledTimes(1));
    expect(withdrawFromUserAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      identifier_type: "phone",
      identifier_value: "+27 82 555 0001",
      amount: "200",
      currency: "ZAR",
      reason: "Cash-out at agent counter",
      bank_mirror_account_id: "mirror-zar-1",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a USD tenant's withdraw dialog defaults to USD, not ZAR", async () => {
    const user = await openDialog("USD", [usdMirror]);

    // The currency field is seeded from the active tenant's currency, so the
    // USD bank mirror is eligible without the operator retyping the currency.
    expect(screen.getByLabelText("Currency")).toHaveValue("USD");

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "200");
    const mirrorSelect = screen.getAllByRole("combobox")[1];
    await user.click(mirrorSelect);
    await user.click(
      await screen.findByRole("option", { name: "Chase — USD settlement" }),
    );
    await user.type(screen.getByLabelText("Reason (audit)"), "Cash-out at agent counter");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() => expect(withdrawFromUserAction).toHaveBeenCalledTimes(1));
    expect(withdrawFromUserAction.mock.calls[0][0]).toMatchObject({
      currency: "USD",
      bank_mirror_account_id: "mirror-usd-1",
    });
  });

  it("Verify a withdrawal is blocked until a bank mirror is chosen", async () => {
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "200");
    await user.type(screen.getByLabelText("Reason (audit)"), "Cash-out at agent counter");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(
      await screen.findByText("Select a bank mirror for the counter-leg."),
    ).toBeInTheDocument();
    expect(withdrawFromUserAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected withdrawal shows the error to the admin", async () => {
    withdrawFromUserAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "insufficient_funds",
      message: "The customer wallet does not hold that much.",
    });
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.type(screen.getByLabelText("Amount"), "200");
    await pickMirror(user);
    await user.type(screen.getByLabelText("Reason (audit)"), "Cash-out at agent counter");
    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    expect(
      await screen.findByText(/insufficient_funds: The customer wallet does not hold/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
