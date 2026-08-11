/**
 * Interaction tests for <MultipliersTable> — rendering and the
 * confirm-guarded hard delete (a destructive config action, so the flow
 * is covered per coding-guidelines §4).
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MultipliersTable } from "@/app/(authenticated)/multipliers/_components/multipliers-table";
import type { BonusMultiplier } from "@/lib/api-types";

const deleteMultiplierAction = vi.fn();
vi.mock("@/app/(authenticated)/multipliers/_actions", () => ({
  deleteMultiplierAction: (...args: unknown[]) => deleteMultiplierAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const MULTIPLIER: BonusMultiplier = {
  id: "mult-1",
  tenant_id: "tenant-1",
  rule_id: null,
  segment_id: null,
  multiplier: "2.00",
  valid_from: null,
  valid_until: null,
  created_at: "2026-08-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  deleteMultiplierAction.mockResolvedValue({ ok: true });
});

function renderTable() {
  render(
    <MultipliersTable multipliers={[MULTIPLIER]} rules={[]} segments={[]} />,
  );
}

describe("Boosting rewards — listing and deleting multipliers", () => {
  it("Verify a tenant-wide multiplier renders factor, scope and status", () => {
    renderTable();

    expect(screen.getByText("×2")).toBeInTheDocument();
    expect(
      screen.getByText("All points rules · All users"),
    ).toBeInTheDocument();
    expect(screen.getByText("Always active")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("Verify deleting a multiplier requires confirmation first", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Delete multiplier" }));

    // Nothing is deleted until the operator confirms in the dialog.
    expect(deleteMultiplierAction).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteMultiplierAction).toHaveBeenCalledTimes(1));
    expect(deleteMultiplierAction).toHaveBeenCalledWith("mult-1", "tenant-1");
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Multiplier deleted" }),
    );
  });

  it("Verify cancelling the confirm dialog deletes nothing", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Delete multiplier" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(deleteMultiplierAction).not.toHaveBeenCalled();
  });

  it("Verify a failed delete surfaces the reason in a toast", async () => {
    deleteMultiplierAction.mockResolvedValue({
      ok: false,
      errorCode: "multiplier_not_found",
      message: "Already deleted.",
    });
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Delete multiplier" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Couldn't delete",
          variant: "danger",
        }),
      ),
    );
  });
});
