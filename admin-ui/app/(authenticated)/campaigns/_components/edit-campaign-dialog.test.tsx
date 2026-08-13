/**
 * Interaction tests for <EditCampaignDialog> — the admin patch form for a
 * campaign's editable fields (name, reward value, status).
 *
 * These drive the (parent-controlled) dialog as an admin does — change the
 * name/reward, save — and assert the update action gets the campaign id, tenant
 * and patched fields, that a non-positive reward is refused before any call,
 * and that a backend rejection keeps the form open. The server action is
 * mocked; no backend is touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditCampaignDialog } from "@/app/(authenticated)/campaigns/_components/edit-campaign-dialog";
import { SEGMENT_GROUPS, SEGMENTS } from "@/app/(authenticated)/campaigns/_components/segment-fixtures";
import type { Rule } from "@/lib/api-types";

const updateCampaignAction = vi.fn();
vi.mock("@/app/(authenticated)/campaigns/_actions", () => ({
  updateCampaignAction: (...args: unknown[]) => updateCampaignAction(...args),
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
  reward_currency: null,
  stop_after_n_triggers: null,
  resets_after_trigger: true,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
};

const onOpenChange = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  updateCampaignAction.mockResolvedValue({ ok: true });
});

/** Render the dialog already open (parent controls its visibility). */
function renderOpen(rule: Rule = RULE) {
  return render(
    <EditCampaignDialog
      rule={rule}
      tenantId="tenant-1"
      segments={SEGMENTS}
      segmentGroups={SEGMENT_GROUPS}
      open
      onOpenChange={onOpenChange}
    />,
  );
}

describe("Managing reward campaigns — editing a campaign", () => {
  it("Verify an admin can rename a campaign and change its reward value", async () => {
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    const name = within(dialog).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Weekly P2P milestone v2");
    const reward = within(dialog).getByLabelText(/Reward value/);
    await user.clear(reward);
    await user.type(reward, "350");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCampaignAction).toHaveBeenCalledTimes(1));
    expect(updateCampaignAction.mock.calls[0]).toEqual([
      "rule-1",
      "tenant-1",
      { name: "Weekly P2P milestone v2", reward_value: "350", status: "active" },
    ]);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Campaign updated" }),
    );
    // A successful save asks the parent to close the dialog.
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("Verify editing is blocked when the reward value is not positive", async () => {
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    const reward = within(dialog).getByLabelText(/Reward value/);
    await user.clear(reward);
    await user.type(reward, "0");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("Reward value must be a positive number."),
    ).toBeInTheDocument();
    expect(updateCampaignAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected edit shows the reason and keeps the form open", async () => {
    updateCampaignAction.mockResolvedValue({
      ok: false,
      errorCode: "rule_locked",
      message: "This campaign is locked while rewards are in flight.",
    });
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText(/This campaign is locked while rewards are in flight\./),
    ).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

describe("Managing reward campaigns — retargeting the audience (WAL-79)", () => {
  it("Verify an admin can retarget an all-users campaign at a segment", async () => {
    const user = userEvent.setup();
    renderOpen();
    const dialog = screen.getByRole("dialog");

    await user.click(within(dialog).getByRole("combobox", { name: "Segment group" }));
    await user.click(await screen.findByRole("option", { name: "Customer Loyalty" }));
    await user.click(within(dialog).getByRole("combobox", { name: "Segment" }));
    await user.click(await screen.findByRole("option", { name: "Silver" }));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCampaignAction).toHaveBeenCalledTimes(1));
    expect(updateCampaignAction.mock.calls[0][2]).toMatchObject({
      segment_id: "seg-silver",
    });
  });

  it("Verify clearing the audience sends an explicit null to unbind", async () => {
    const user = userEvent.setup();
    renderOpen({ ...RULE, segment_id: "seg-gold" });
    const dialog = screen.getByRole("dialog");

    await user.click(within(dialog).getByRole("combobox", { name: "Segment group" }));
    await user.click(await screen.findByRole("option", { name: "All users" }));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCampaignAction).toHaveBeenCalledTimes(1));
    expect(updateCampaignAction.mock.calls[0][2]).toMatchObject({
      segment_id: null,
    });
  });

  it("Verify untouched targeting is omitted so the binding is preserved", async () => {
    const user = userEvent.setup();
    renderOpen({ ...RULE, segment_id: "seg-gold" });
    const dialog = screen.getByRole("dialog");

    const name = within(dialog).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Renamed, still Gold-only");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCampaignAction).toHaveBeenCalledTimes(1));
    // Omitted ≠ null: null would CLEAR the binding on the backend.
    expect(updateCampaignAction.mock.calls[0][2]).not.toHaveProperty("segment_id");
  });
});
