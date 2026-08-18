/**
 * Interaction tests for CreateInstrumentDialog from the admin operator's chair.
 *
 * An admin adds a new value unit (currency or points) to the tenant catalog.
 * These drive the real form — fill it, optionally opt into backfill, submit —
 * and assert the outcomes the admin cares about: the instrument is created with
 * the entered details, an invalid code is rejected before anything is sent, and
 * a backend rejection is surfaced. The route's server action is mocked; no
 * backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateInstrumentDialog } from "@/app/(authenticated)/instruments/_components/create-instrument-dialog";

const createInstrumentAction = vi.fn();
vi.mock("@/app/(authenticated)/instruments/_actions", () => ({
  createInstrumentAction: (...args: unknown[]) => createInstrumentAction(...args),
}));

async function openDialog() {
  const user = userEvent.setup();
  render(
    <CreateInstrumentDialog
      pointsAvailable
      tenantId="tenant-1"
      trigger={<button type="button">New instrument</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New instrument" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create an instrument", () => {
  it("Verify an admin can add a new instrument to the tenant catalog", async () => {
    createInstrumentAction.mockResolvedValue({ ok: true });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "usdc");
    await user.type(screen.getByLabelText("Symbol"), "$");
    await user.type(screen.getByLabelText("Display name"), "USD Coin");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createInstrumentAction).toHaveBeenCalledTimes(1));
    expect(createInstrumentAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "tenant-1",
      code: "USDC", // the input upper-cases the code as it is typed
      symbol: "$",
      display_name: "USD Coin",
      account_type: "financial_wallet",
      assign_to_existing_users: false,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify an admin can backfill accounts for existing users when adding an instrument", async () => {
    createInstrumentAction.mockResolvedValue({ ok: true });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "usdc");
    await user.type(screen.getByLabelText("Symbol"), "$");
    await user.type(screen.getByLabelText("Display name"), "USD Coin");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createInstrumentAction).toHaveBeenCalledTimes(1));
    expect(createInstrumentAction.mock.calls[0][0]).toMatchObject({
      assign_to_existing_users: true,
    });
  });

  it("Verify an invalid instrument code is rejected before anything is sent", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "1coin");
    await user.type(screen.getByLabelText("Symbol"), "$");
    await user.type(screen.getByLabelText("Display name"), "One Coin");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/Code must be uppercase letters/)).toBeInTheDocument();
    expect(createInstrumentAction).not.toHaveBeenCalled();
  });

  it("Verify a failed instrument creation shows the error to the admin", async () => {
    createInstrumentAction.mockResolvedValue({
      ok: false,
      errorCode: "code_taken",
      message: "An instrument with that code already exists.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "usdc");
    await user.type(screen.getByLabelText("Symbol"), "$");
    await user.type(screen.getByLabelText("Display name"), "USD Coin");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/code_taken: An instrument with that code already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
