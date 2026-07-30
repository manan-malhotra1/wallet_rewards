/**
 * Interaction tests for SweepButton from the admin operator's chair.
 *
 * An admin kicks off a reconciliation sweep of stuck redemptions. These drive
 * the real button — click it — and assert the outcomes the admin cares about:
 * the sweep runs for the active tenant and its result counts are surfaced, and
 * a failed sweep is surfaced as an error. The route's server action and the
 * toast surface are mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SweepButton } from "@/app/(authenticated)/reconciliation/_components/sweep-button";

const triggerSweepAction = vi.fn();
vi.mock("@/app/(authenticated)/reconciliation/_actions", () => ({
  triggerSweepAction: (...args: unknown[]) => triggerSweepAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Run a reconciliation sweep", () => {
  it("Verify an admin can run a reconciliation sweep", async () => {
    triggerSweepAction.mockResolvedValue({
      ok: true,
      scanned: 12,
      bumped: 3,
      escalated: 1,
    });
    const user = userEvent.setup();
    render(<SweepButton tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: /Sweep now/ }));

    await waitFor(() => expect(triggerSweepAction).toHaveBeenCalledWith("tenant-1"));
    // The admin sees the sweep result counts.
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Sweep complete",
          description: expect.stringContaining("Scanned 12"),
        }),
      ),
    );
    // The button re-enables once the sweep resolves.
    expect(screen.getByRole("button", { name: /Sweep now/ })).toBeEnabled();
  });

  it("Verify an admin sees an error when a reconciliation sweep fails", async () => {
    triggerSweepAction.mockResolvedValue({
      ok: false,
      errorCode: "backend_unavailable",
      message: "The reconciliation service is unreachable.",
    });
    const user = userEvent.setup();
    render(<SweepButton tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: /Sweep now/ }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Sweep failed",
          variant: "danger",
          description: expect.stringContaining("backend_unavailable"),
        }),
      ),
    );
  });
});
