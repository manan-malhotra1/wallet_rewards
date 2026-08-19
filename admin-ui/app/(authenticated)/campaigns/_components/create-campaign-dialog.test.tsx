/**
 * Interaction tests for <CreateCampaignDialog> — the two-step reward-rule
 * wizard an admin uses to stand up a campaign (a rule, on the backend).
 *
 * These drive the wizard as an admin does — pick the rule type on step 1, fill
 * the type-specific fields on step 2, activate — and assert the payload handed
 * to `createCampaignWithBudgetAction` for two different rule types, that a
 * campaign missing its name/reward is refused before any call, and that a
 * backend rejection is surfaced in the form. The server action is mocked; no
 * backend is touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateCampaignDialog } from "@/app/(authenticated)/campaigns/_components/create-campaign-dialog";
import { SEGMENT_GROUPS, SEGMENTS } from "@/app/(authenticated)/campaigns/_components/segment-fixtures";
import type { Service } from "@/lib/api-types";

const createCampaignWithBudgetAction = vi.fn();
vi.mock("@/app/(authenticated)/campaigns/_actions", () => ({
  createCampaignWithBudgetAction: (...args: unknown[]) =>
    createCampaignWithBudgetAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const SERVICES: Service[] = [
  {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P Transfer",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    readiness: null,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  createCampaignWithBudgetAction.mockResolvedValue({
    ok: true,
    campaignId: "rule-1",
    budgetCreated: false,
  });
});

/** Open the wizard and pick a rule type on step 1, landing on step 2. */
async function openWizardAt(
  user: ReturnType<typeof userEvent.setup>,
  typeLabel: string,
) {
  render(
    <CreateCampaignDialog
      tenantId="tenant-1"
      services={SERVICES}
      segments={SEGMENTS}
      segmentGroups={SEGMENT_GROUPS}
      financialCurrencies={["ZAR", "USD"]}
      pointsCurrency="PTS"
      trigger={<button type="button">New campaign</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New campaign" }));
  await screen.findByRole("dialog");
  await user.click(screen.getByRole("button", { name: new RegExp(typeLabel) }));
}

describe("Managing reward campaigns — creating a campaign", () => {
  it("Verify an admin can create a milestone reward rule", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Weekly P2P milestone");
    await user.type(screen.getByLabelText("Count threshold"), "5");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(createCampaignWithBudgetAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "tenant-1",
      name: "Weekly P2P milestone",
      rule_type: "milestone",
      transaction_type: "p2p",
      count_threshold: 5,
      reward_type: "points",
      reward_value: "200",
    });
    // No inline budget requested → second arg is omitted.
    expect(createCampaignWithBudgetAction.mock.calls[0][1]).toBeUndefined();
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Campaign activated" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify an admin can create a first-time reward rule", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "First-time");

    await user.type(screen.getByLabelText("Name"), "Welcome bonus");
    await user.type(screen.getByLabelText("Reward value"), "50");
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(createCampaignWithBudgetAction.mock.calls[0][0]).toMatchObject({
      name: "Welcome bonus",
      rule_type: "first_time",
      transaction_type: "p2p",
      reward_type: "points",
      reward_value: "50",
    });
  });

  it("Verify a points campaign hides the reward-currency dropdown and sends no currency", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    // Reward type defaults to Points → no currency picker.
    expect(screen.queryByLabelText("Reward currency")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Name"), "Points milestone");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(
      createCampaignWithBudgetAction.mock.calls[0][0].reward_currency,
    ).toBeUndefined();
  });

  it("Verify a cashback campaign shows the reward-currency dropdown and threads it into the payload", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Cashback milestone");
    await user.type(screen.getByLabelText("Reward value"), "10");

    // Switch reward type to Cashback → currency picker appears, defaulting
    // to the tenant's first financial currency (ZAR).
    await user.click(screen.getByLabelText("Reward type"));
    await user.click(screen.getByRole("option", { name: "Cashback" }));
    expect(await screen.findByLabelText("Reward currency")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(createCampaignWithBudgetAction.mock.calls[0][0]).toMatchObject({
      reward_type: "cashback",
      reward_currency: "ZAR",
    });
  });

  it("Verify a campaign is blocked without a name and reward value", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    expect(
      await screen.findByText("Name and reward value are required."),
    ).toBeInTheDocument();
    expect(createCampaignWithBudgetAction).not.toHaveBeenCalled();
  });

  it("Verify a failed campaign creation shows the backend error", async () => {
    createCampaignWithBudgetAction.mockResolvedValue({
      ok: false,
      errorCode: "pricing_config_missing",
      message: "No pricing config resolves for this reward.",
    });
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Weekly P2P milestone");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    expect(
      await screen.findByText(/pricing_config_missing/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("Managing reward campaigns — audience targeting (WAL-79)", () => {
  it("Verify a campaign left on All users sends no segment binding", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Everyone milestone");
    await user.type(screen.getByLabelText("Count threshold"), "5");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(createCampaignWithBudgetAction.mock.calls[0][0].segment_id).toBeUndefined();
  });

  it("Verify picking a group narrows the segment options to that group", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.click(screen.getByRole("combobox", { name: "Segment group" }));
    await user.click(await screen.findByRole("option", { name: "Customer Loyalty" }));
    await user.click(screen.getByRole("combobox", { name: "Segment" }));

    expect(await screen.findByRole("option", { name: "Gold" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Silver" })).toBeInTheDocument();
    // High Rollers lives in Transaction Value — the cascade must hide it.
    expect(screen.queryByRole("option", { name: "High Rollers" })).toBeNull();
  });

  it("Verify a targeted campaign sends the chosen segment", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Gold-only milestone");
    await user.type(screen.getByLabelText("Count threshold"), "5");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("combobox", { name: "Segment group" }));
    await user.click(await screen.findByRole("option", { name: "Customer Loyalty" }));
    await user.click(screen.getByRole("combobox", { name: "Segment" }));
    await user.click(await screen.findByRole("option", { name: "Gold" }));
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    await waitFor(() =>
      expect(createCampaignWithBudgetAction).toHaveBeenCalledTimes(1),
    );
    expect(createCampaignWithBudgetAction.mock.calls[0][0]).toMatchObject({
      segment_id: "seg-gold",
    });
  });

  it("Verify a group without a chosen segment is refused before submitting", async () => {
    const user = userEvent.setup();
    await openWizardAt(user, "Milestone");

    await user.type(screen.getByLabelText("Name"), "Half-targeted milestone");
    await user.type(screen.getByLabelText("Count threshold"), "5");
    await user.type(screen.getByLabelText("Reward value"), "200");
    await user.click(screen.getByRole("combobox", { name: "Segment group" }));
    await user.click(await screen.findByRole("option", { name: "Customer Loyalty" }));
    await user.click(screen.getByRole("button", { name: "Activate campaign" }));

    expect(
      await screen.findByText(/Choose a segment in the selected group/),
    ).toBeInTheDocument();
    expect(createCampaignWithBudgetAction).not.toHaveBeenCalled();
  });
});
