/**
 * Interaction tests for <CampaignsTable> — the campaigns list and its per-row
 * View / Edit / Deactivate actions, driven from a rewards admin's chair.
 *
 * Each row exposes three icon buttons that open a different surface (detail
 * drawer, edit dialog, deactivate dialog). These tests assert that wiring: the
 * right action opens the right surface for the row it belongs to. The three
 * child surfaces are stubbed to markers that reflect their `open` prop — their
 * internals are covered by their own suites.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignsTable } from "@/app/(authenticated)/campaigns/_components/campaigns-table";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Rule, RulePerformance } from "@/lib/api-types";

// Stub the three action surfaces to markers keyed on their `open` prop.
vi.mock("./campaign-detail-drawer", () => ({
  CampaignDetailDrawer: ({ open }: { open: boolean }) =>
    open ? <div>campaign detail drawer</div> : null,
}));
vi.mock("./edit-campaign-dialog", () => ({
  EditCampaignDialog: ({ open }: { open: boolean }) =>
    open ? <div>edit campaign dialog</div> : null,
}));
vi.mock("./delete-campaign-dialog", () => ({
  DeleteCampaignDialog: ({ open }: { open: boolean }) =>
    open ? <div>deactivate campaign dialog</div> : null,
}));

const rule: Rule = {
  id: "rule-1",
  tenant_id: "tenant-1",
  name: "Winter Cashback",
  description: null,
  rule_type: "campaign",
  transaction_type: "send",
  count_threshold: 1,
  min_amount: null,
  time_window: null,
  streak_units: null,
  streak_unit_window: null,
  campaign_start_date: "2026-06-01",
  campaign_end_date: "2026-08-31",
  reward_type: "cashback",
  reward_value: "10",
  reward_currency: "ZAR",
  stop_after_n_triggers: null,
  resets_after_trigger: false,
  status: "active",
  created_at: "2026-06-01T00:00:00Z",
};

const performance: Record<string, RulePerformance | null> = {
  "rule-1": {
    rule_id: "rule-1",
    total_fires: 42,
    unique_users_rewarded: 30,
    total_reward_value: "420",
    first_fired_at: "2026-06-02T00:00:00Z",
    last_fired_at: "2026-07-20T00:00:00Z",
    budget_scope: "tenant_only",
  },
};

function renderTable() {
  render(
    <TooltipProvider>
      <CampaignsTable rules={[rule]} performance={performance} tenantId="tenant-1" />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Campaigns — table row actions", () => {
  it("Verify an admin can open a campaign's details from its row", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "View campaign" }));

    expect(screen.getByText("campaign detail drawer")).toBeInTheDocument();
    expect(screen.queryByText("edit campaign dialog")).not.toBeInTheDocument();
  });

  it("Verify an admin can open the edit dialog for a campaign from its row", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Edit campaign" }));

    expect(screen.getByText("edit campaign dialog")).toBeInTheDocument();
    expect(screen.queryByText("deactivate campaign dialog")).not.toBeInTheDocument();
  });

  it("Verify an admin can open the deactivate dialog for a campaign from its row", async () => {
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "Deactivate campaign" }));

    expect(screen.getByText("deactivate campaign dialog")).toBeInTheDocument();
    expect(screen.queryByText("campaign detail drawer")).not.toBeInTheDocument();
  });
});
