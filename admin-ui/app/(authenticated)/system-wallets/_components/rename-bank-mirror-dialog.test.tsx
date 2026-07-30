/**
 * Interaction tests for RenameBankMirrorDialog from the admin operator's chair.
 *
 * An operator clicks the pencil next to a bank mirror, edits its label and
 * saves. These tests confirm the rename action is called with the new label,
 * that an emptied name is refused, and that a name collision is surfaced. The
 * server action is mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RenameBankMirrorDialog } from "@/app/(authenticated)/system-wallets/_components/rename-bank-mirror-dialog";
import type { SystemWallet } from "@/lib/api-types";

const renameBankMirrorAction = vi
  .fn()
  .mockResolvedValue({ ok: true, message: "Renamed." });
vi.mock("@/app/(authenticated)/system-wallets/_actions", () => ({
  renameBankMirrorAction: (...args: unknown[]) => renameBankMirrorAction(...args),
}));

const account: SystemWallet = {
  id: "acct-1",
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
  render(<RenameBankMirrorDialog account={account} tenantId="tenant-1" />);
  await user.click(
    screen.getByRole("button", { name: "Rename Standard Bank — main float" }),
  );
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Rename a bank mirror", () => {
  it("Verify an admin can rename a bank mirror", async () => {
    const user = await openDialog();

    const nameField = screen.getByLabelText("Name");
    await user.clear(nameField);
    await user.type(nameField, "Standard Bank — settlement");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(renameBankMirrorAction).toHaveBeenCalledTimes(1));
    expect(renameBankMirrorAction.mock.calls[0]).toEqual([
      "tenant-1",
      "acct-1",
      "Standard Bank — settlement",
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify renaming is blocked when the name is cleared", async () => {
    const user = await openDialog();

    await user.clear(screen.getByLabelText("Name"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(renameBankMirrorAction).not.toHaveBeenCalled();
  });

  it("Verify a rename collision shows the error to the admin", async () => {
    renameBankMirrorAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "duplicate_name",
      message: "Another bank mirror already uses that name.",
    });
    const user = await openDialog();

    const nameField = screen.getByLabelText("Name");
    await user.clear(nameField);
    await user.type(nameField, "Chase — USD settlement");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(/duplicate_name: Another bank mirror already uses that name/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
