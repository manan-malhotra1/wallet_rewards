/**
 * Interaction tests for <AddIdentifierDialog> — adding an identifier to an
 * existing customer (Epic 27, Story 27.2).
 *
 * Admin-added identifiers land unverified and apply immediately (not
 * maker-checker). These tests drive the dialog as an admin (open, type a value,
 * add) and assert the action args + refresh on success, the blank-value guard,
 * and the friendly duplicate-identifier surface.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddIdentifierDialog } from "@/app/(authenticated)/users/_components/add-identifier-dialog";

const addIdentifierAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  addIdentifierAction: (...args: unknown[]) => addIdentifierAction(...args),
}));

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  addIdentifierAction.mockResolvedValue({ ok: true, verified: false });
});

/** Open the dialog and return its content node. */
async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  render(<AddIdentifierDialog userId="user-1" tenantId="tenant-1" />);
  await user.click(screen.getByRole("button", { name: "Add identifier" }));
  return screen.getByRole("dialog");
}

describe("Managing customers — adding an identifier", () => {
  it("Verify an admin can add a phone identifier to a customer", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Value"), "+27825550142");
    await user.click(within(dialog).getByRole("button", { name: "Add identifier" }));

    await waitFor(() => expect(addIdentifierAction).toHaveBeenCalledTimes(1));
    // Default type is phone; the trimmed value is passed through unchanged.
    expect(addIdentifierAction).toHaveBeenCalledWith("user-1", "tenant-1", {
      identifier_type: "phone",
      identifier_value: "+27825550142",
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Identifier added" }),
    );
    // The server-rendered detail card is refreshed so the new row appears.
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("Verify adding an identifier with no value is blocked", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByRole("button", { name: "Add identifier" }));

    expect(await screen.findByText("Enter an identifier value.")).toBeInTheDocument();
    expect(addIdentifierAction).not.toHaveBeenCalled();
  });

  it("Verify adding an identifier already in use shows a friendly error", async () => {
    addIdentifierAction.mockResolvedValue({
      ok: false,
      errorCode: "identifier_already_in_use",
      message: "That identifier is already registered.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Value"), "+27825550142");
    await user.click(within(dialog).getByRole("button", { name: "Add identifier" }));

    expect(
      await screen.findByText("That identifier is already registered."),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
