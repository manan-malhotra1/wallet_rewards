/**
 * Interaction tests for <ResetPinButton> — the admin "Reset PIN" affordance.
 *
 * A reset is guarded by a confirm dialog and, today, reveals the fresh PIN
 * inline so the operator can read it back over a verified channel. These tests
 * drive it as an admin (open, confirm) and assert the action fires only on
 * confirmation, the new PIN is shown on success, and a failure surfaces inline.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPinButton } from "@/app/(authenticated)/users/_components/reset-pin-button";

const resetUserPinAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  resetUserPinAction: (...args: unknown[]) => resetUserPinAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  resetUserPinAction.mockResolvedValue({
    ok: true,
    deliveredVia: "inline",
    newPin: "4821",
  });
});

describe("Managing customers — PIN reset", () => {
  it("Verify a PIN reset asks for confirmation before anything changes", async () => {
    const user = userEvent.setup();
    render(<ResetPinButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Reset PIN" }));

    expect(await screen.findByText("Reset this user's PIN?")).toBeInTheDocument();
    expect(resetUserPinAction).not.toHaveBeenCalled();
  });

  it("Verify a PIN reset can be triggered for a customer and reveals the new PIN", async () => {
    const user = userEvent.setup();
    render(<ResetPinButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Reset PIN" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reset PIN" }));

    await waitFor(() => expect(resetUserPinAction).toHaveBeenCalledWith("user-1", "tenant-1"));
    // The freshly generated PIN is shown so the admin can read it back.
    expect(await screen.findByText("PIN reset")).toBeInTheDocument();
    expect(screen.getByText("4821")).toBeInTheDocument();
  });

  it("Verify a failed PIN reset shows the reason", async () => {
    resetUserPinAction.mockResolvedValue({
      ok: false,
      errorCode: "internal_error",
      message: "PIN service unavailable.",
    });
    const user = userEvent.setup();
    render(<ResetPinButton userId="user-1" tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Reset PIN" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reset PIN" }));

    expect(await screen.findByText("Couldn't reset")).toBeInTheDocument();
    expect(screen.getByText(/PIN service unavailable\./)).toBeInTheDocument();
    // Stays on the confirm stage — no PIN is revealed.
    expect(screen.queryByText("4821")).not.toBeInTheDocument();
  });
});
