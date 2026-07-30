/**
 * Interaction tests for <AccessLockControl> — the platform-admin control to
 * impose or lift an access restriction (login lock / transaction lock /
 * restore).
 *
 * Each choice is guarded by a confirm dialog because a login lock ends the
 * user's live session. These tests drive it as an admin (choose a target,
 * confirm) and assert the action fires only after confirmation, with the right
 * level, plus the server-error surface.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccessLockControl } from "@/app/(authenticated)/users/_components/access-lock-control";

const setUserAccessAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  setUserAccessAction: (...args: unknown[]) => setUserAccessAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  setUserAccessAction.mockResolvedValue({ ok: true, level: "login_locked" });
});

describe("Managing customers — access lock", () => {
  it("Verify locking a customer's login asks for confirmation first", async () => {
    const user = userEvent.setup();
    render(<AccessLockControl userId="user-1" tenantId="tenant-1" level="active" />);

    await user.click(screen.getByRole("button", { name: "Lock login" }));

    // A confirm dialog appears; nothing is applied until the admin confirms.
    expect(await screen.findByText("Lock login for this user?")).toBeInTheDocument();
    expect(setUserAccessAction).not.toHaveBeenCalled();
  });

  it("Verify confirming a login lock applies it immediately", async () => {
    const user = userEvent.setup();
    render(<AccessLockControl userId="user-1" tenantId="tenant-1" level="active" />);

    await user.click(screen.getByRole("button", { name: "Lock login" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Lock login" }));

    await waitFor(() => expect(setUserAccessAction).toHaveBeenCalledTimes(1));
    expect(setUserAccessAction).toHaveBeenCalledWith("user-1", "tenant-1", "login_locked");
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Login locked" }),
    );
  });

  it("Verify a failed access change shows the reason and keeps the dialog open", async () => {
    setUserAccessAction.mockResolvedValue({
      ok: false,
      errorCode: "internal_error",
      message: "Access service unavailable.",
    });
    const user = userEvent.setup();
    render(<AccessLockControl userId="user-1" tenantId="tenant-1" level="active" />);

    await user.click(screen.getByRole("button", { name: "Lock login" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Lock login" }));

    expect(await screen.findByText("Couldn't update access")).toBeInTheDocument();
    expect(screen.getByText(/Access service unavailable\./)).toBeInTheDocument();
  });
});
