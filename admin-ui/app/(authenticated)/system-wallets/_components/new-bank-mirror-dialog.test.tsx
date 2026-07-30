/**
 * Interaction tests for NewBankMirrorDialog from the admin operator's chair.
 *
 * An operator registers a named bank-mirror account (one per real bank
 * account) and picks its currency. These tests confirm the create action is
 * proposed with the entered name and chosen currency, that a name is required,
 * and that a duplicate-name rejection is surfaced. The server action is mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewBankMirrorDialog } from "@/app/(authenticated)/system-wallets/_components/new-bank-mirror-dialog";

const createBankMirrorAction = vi
  .fn()
  .mockResolvedValue({ ok: true, message: "Proposed." });
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  createBankMirrorAction: (...args: unknown[]) => createBankMirrorAction(...args),
}));

async function openDialog(
  defaultCurrency = "ZAR",
  currencies: string[] = ["ZAR", "USD"],
) {
  const user = userEvent.setup();
  render(
    <NewBankMirrorDialog
      tenantId="tenant-1"
      currencies={currencies}
      defaultCurrency={defaultCurrency}
      trigger={<button type="button">New bank mirror</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New bank mirror" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create a bank mirror", () => {
  it("Verify an admin can create a named bank mirror", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Standard Bank — main float");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createBankMirrorAction).toHaveBeenCalledTimes(1));
    expect(createBankMirrorAction.mock.calls[0]).toEqual([
      "tenant-1",
      { name: "Standard Bank — main float", currency: "ZAR" },
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a USD tenant's bank-mirror dialog defaults to USD, not ZAR", async () => {
    const user = await openDialog("USD");

    // The currency select is seeded to the active tenant's currency.
    expect(screen.getByRole("combobox")).toHaveTextContent("USD");

    await user.type(screen.getByLabelText("Name"), "Chase — USD settlement");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createBankMirrorAction).toHaveBeenCalledTimes(1));
    expect(createBankMirrorAction.mock.calls[0][1]).toEqual({
      name: "Chase — USD settlement",
      currency: "USD",
    });
  });

  it("Verify an admin can create a bank mirror in a chosen currency", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Chase — USD settlement");
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "USD" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createBankMirrorAction).toHaveBeenCalledTimes(1));
    expect(createBankMirrorAction.mock.calls[0][1]).toEqual({
      name: "Chase — USD settlement",
      currency: "USD",
    });
  });

  it("Verify creating a bank mirror is blocked when the name is empty", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(createBankMirrorAction).not.toHaveBeenCalled();
  });

  it("Verify a duplicate bank mirror name shows the error to the admin", async () => {
    createBankMirrorAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "duplicate_name",
      message: "A bank mirror with that name already exists.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Standard Bank — main float");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/duplicate_name: A bank mirror with that name already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
