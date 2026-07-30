/**
 * Interaction tests for <UnlockButton> — the platform-admin button that releases
 * a customer's PIN lockout WITHOUT changing their PIN (distinct from Reset PIN).
 *
 * The action is guarded by a confirm dialog. These tests drive it as an admin
 * (open, confirm) and assert the action fires only on confirmation, plus the
 * server-error surface.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnlockButton } from "@/app/(authenticated)/users/_components/unlock-button";

const unlockUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  unlockUserAction: (...args: unknown[]) => unlockUserAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  unlockUserAction.mockResolvedValue({ ok: true, wasLocked: true });
});

describe("Managing customers — clearing a PIN lockout", () => {
  it("Verify unlocking a customer asks for confirmation first", async () => {
    const user = userEvent.setup();
    render(<UnlockButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(await screen.findByText("Unlock this user?")).toBeInTheDocument();
    expect(unlockUserAction).not.toHaveBeenCalled();
  });

  it("Verify confirming an unlock clears the customer's PIN lockout", async () => {
    const user = userEvent.setup();
    render(<UnlockButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Unlock" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Unlock" }));

    await waitFor(() => expect(unlockUserAction).toHaveBeenCalledWith("user-1", "tenant-1"));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "User unlocked" }),
    );
  });

  it("Verify a failed unlock shows the reason", async () => {
    unlockUserAction.mockResolvedValue({
      ok: false,
      errorCode: "internal_error",
      message: "Lockout service unavailable.",
    });
    const user = userEvent.setup();
    render(<UnlockButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Unlock" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Unlock" }));

    expect(await screen.findByText("Couldn't unlock")).toBeInTheDocument();
    expect(screen.getByText(/Lockout service unavailable\./)).toBeInTheDocument();
  });
});
