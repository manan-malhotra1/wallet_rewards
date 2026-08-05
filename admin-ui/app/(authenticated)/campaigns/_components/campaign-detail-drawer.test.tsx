/**
 * Interaction tests for <CampaignDetailDrawer> — the view-only side panel that
 * shows a campaign's full configuration, budget scope and live performance.
 *
 * These render the (parent-controlled) drawer as an admin sees it and assert
 * the panel reads back the campaign's configuration and its recorded
 * performance, that a campaign with no activity shows placeholders instead of
 * numbers, and that the close control asks the parent to dismiss it. No server
 * action is involved — this panel is read-only.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignDetailDrawer } from "@/app/(authenticated)/campaigns/_components/campaign-detail-drawer";
import type { Rule, RulePerformance } from "@/lib/api-types";

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

const PERFORMANCE: RulePerformance = {
  rule_id: "rule-1",
  total_fires: 1234,
  unique_users_rewarded: 456,
  total_reward_value: "246800",
  first_fired_at: "2026-02-01T10:00:00Z",
  last_fired_at: "2026-07-01T10:00:00Z",
  budget_scope: "both",
};

const onOpenChange = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Managing reward campaigns — viewing a campaign", () => {
  it("Verify an admin can review a campaign's full configuration and performance", async () => {
    render(
      <CampaignDetailDrawer
        rule={RULE}
        performance={PERFORMANCE}
        open
        onOpenChange={onOpenChange}
      />,
    );
    const drawer = screen.getByRole("dialog");

    // Configuration reads back.
    expect(within(drawer).getByText("Weekly P2P milestone")).toBeInTheDocument();
    expect(within(drawer).getByText("milestone")).toBeInTheDocument();
    expect(within(drawer).getByText("200 points")).toBeInTheDocument();
    expect(within(drawer).getByText("5")).toBeInTheDocument();
    // Performance reads back with thousands separators.
    expect(within(drawer).getByText("1,234")).toBeInTheDocument();
    expect(within(drawer).getByText("456")).toBeInTheDocument();
    // Budget scope is described in plain English.
    expect(
      within(drawer).getByText(/both per-campaign cap AND tenant-wide cap/),
    ).toBeInTheDocument();
  });

  it("Verify a campaign with no recorded activity shows placeholders", () => {
    render(
      <CampaignDetailDrawer
        rule={RULE}
        performance={null}
        open
        onOpenChange={onOpenChange}
      />,
    );
    const drawer = screen.getByRole("dialog");

    // With no performance payload, the budget line falls back to a dash and no
    // performance metrics are rendered.
    expect(within(drawer).getByText("—")).toBeInTheDocument();
    expect(within(drawer).queryByText("Total fires")).not.toBeInTheDocument();
  });

  it("Verify closing the detail panel dismisses it", async () => {
    const user = userEvent.setup();
    render(
      <CampaignDetailDrawer
        rule={RULE}
        performance={PERFORMANCE}
        open
        onOpenChange={onOpenChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Close drawer" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
