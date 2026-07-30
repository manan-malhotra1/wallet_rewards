/**
 * Interaction tests for <DeleteCampaignDialog> — the confirm-before-deactivate
 * dialog.
 *
 * Deactivating a campaign is a destructive, confirm-gated action: the dialog
 * must never call the delete action on render or on cancel — only once the
 * admin explicitly confirms. These tests lock in that gate, the confirmed
 * happy path (soft-delete with the right id/tenant), and that a backend failure
 * is surfaced without closing. The server action is mocked; no backend is
 * touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteCampaignDialog } from "@/app/(authenticated)/campaigns/_components/delete-campaign-dialog";
import type { Rule } from "@/lib/api-types";

const deleteCampaignAction = vi.fn();
vi.mock("@/app/(authenticated)/campaigns/_actions", () => ({
  deleteCampaignAction: (...args: unknown[]) => deleteCampaignAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const RULE: Rule = {
  id: "rule-1",
  tenant_id: "tenant-1",
  name: "Weekly P2P milestone",
  description: null,
  rule_type: "milestone",
  transaction_type: "p2p",
  count_threshold: 5,
  min_amount: null,
  time_window: "rolling_7d",
  streak_units: null,
  streak_unit_window: null,
  campaign_start_date: null,
  campaign_end_date: null,
  reward_type: "points",
  reward_value: "200",
  stop_after_n_triggers: null,
  resets_after_trigger: true,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const onOpenChange = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  deleteCampaignAction.mockResolvedValue({ ok: true });
});

/** Render the dialog already open (parent controls its visibility). */
function renderOpen() {
  return render(
    <DeleteCampaignDialog
      rule={RULE}
      tenantId="tenant-1"
      open
      onOpenChange={onOpenChange}
    />,
  );
}

describe("Managing reward campaigns — deactivating a campaign", () => {
  it("Verify deactivating a campaign asks for confirmation first", async () => {
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    // The dialog is on screen naming the campaign, but nothing has fired yet.
    expect(within(dialog).getByText("Weekly P2P milestone")).toBeInTheDocument();
    expect(deleteCampaignAction).not.toHaveBeenCalled();

    // Cancelling closes without ever calling the action.
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(deleteCampaignAction).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("Verify an admin can deactivate a campaign after confirming", async () => {
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(deleteCampaignAction).toHaveBeenCalledTimes(1));
    expect(deleteCampaignAction.mock.calls[0]).toEqual(["rule-1", "tenant-1"]);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Campaign deactivated" }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("Verify a failed deactivation shows the reason and keeps the dialog open", async () => {
    deleteCampaignAction.mockResolvedValue({
      ok: false,
      errorCode: "not_found",
      message: "That campaign no longer exists.",
    });
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    expect(
      await screen.findByText(/That campaign no longer exists\./),
    ).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
