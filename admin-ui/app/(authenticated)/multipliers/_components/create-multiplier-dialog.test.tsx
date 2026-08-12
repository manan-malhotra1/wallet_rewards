/**
 * Interaction tests for <CreateMultiplierDialog> — the "New multiplier" form.
 *
 * Drives the dialog the way an operator does — open, set a factor, scope it,
 * submit — and asserts what the operator cares about: the action receives the
 * right payload (sentinel "all" scopes omitted), a bad factor is refused
 * before anything is sent, cashback rules never appear in the rule picker,
 * and a backend rejection stays visible. The server action is mocked.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateMultiplierDialog } from "@/app/(authenticated)/multipliers/_components/create-multiplier-dialog";
import type { Rule, Segment } from "@/lib/api-types";

const createMultiplierAction = vi.fn();
vi.mock("@/app/(authenticated)/multipliers/_actions", () => ({
  createMultiplierAction: (...args: unknown[]) => createMultiplierAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

/** Minimal Rule fixture — only the fields the dialog reads matter. */
function makeRule(overrides: Partial<Rule>): Rule {
  return {
    id: "rule-1",
    tenant_id: "tenant-1",
    name: "First fund bonus",
    description: null,
    rule_type: "first_time",
    transaction_type: "fund",
    count_threshold: null,
    min_amount: null,
    time_window: null,
    streak_units: null,
    streak_unit_window: null,
    campaign_start_date: null,
    campaign_end_date: null,
    reward_type: "points",
    reward_value: "100",
    reward_currency: null,
    stop_after_n_triggers: null,
    resets_after_trigger: true,
    status: "active",
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

const SEGMENTS: Segment[] = [
  {
    id: "seg-1",
    tenant_id: "tenant-1",
    name: "vip-users",
    description: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    group_id: "group-1",
    priority: 0,
    criteria: null,
    is_system: false,
    last_evaluated_at: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  createMultiplierAction.mockResolvedValue({ ok: true });
});

/** Render + open the dialog and return its content node. */
async function openDialog(
  user: ReturnType<typeof userEvent.setup>,
  rules: Rule[] = [makeRule({})],
) {
  render(
    <CreateMultiplierDialog
      tenantId="tenant-1"
      rules={rules}
      segments={SEGMENTS}
      trigger={<button type="button">New multiplier</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New multiplier" }));
  return screen.findByRole("dialog");
}

describe("Boosting rewards — creating a bonus multiplier", () => {
  it("Verify an admin can create a tenant-wide multiplier", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Factor"), "2");
    await user.click(
      within(dialog).getByRole("button", { name: "Create multiplier" }),
    );

    await waitFor(() => expect(createMultiplierAction).toHaveBeenCalledTimes(1));
    // Both scopes left at "all" → omitted so the backend stores NULLs.
    expect(createMultiplierAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      rule_id: undefined,
      segment_id: undefined,
      multiplier: "2",
      valid_from: undefined,
      valid_until: undefined,
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Multiplier created" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("Verify a multiplier can be scoped to a rule and a segment", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Factor"), "1.5");
    await user.click(within(dialog).getByRole("combobox", { name: "Rule scope" }));
    await user.click(await screen.findByRole("option", { name: "First fund bonus" }));
    await user.click(
      within(dialog).getByRole("combobox", { name: "Segment scope" }),
    );
    await user.click(await screen.findByRole("option", { name: "vip-users" }));
    await user.click(
      within(dialog).getByRole("button", { name: "Create multiplier" }),
    );

    await waitFor(() => expect(createMultiplierAction).toHaveBeenCalledTimes(1));
    expect(createMultiplierAction.mock.calls[0][0]).toMatchObject({
      rule_id: "rule-1",
      segment_id: "seg-1",
      multiplier: "1.5",
    });
  });

  it("Verify a multiplier cannot be created without a positive factor", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(
      within(dialog).getByRole("button", { name: "Create multiplier" }),
    );

    expect(
      await screen.findByText(/Factor must be a positive number/),
    ).toBeInTheDocument();
    expect(createMultiplierAction).not.toHaveBeenCalled();
  });

  it("Verify an inverted validity window is refused before submitting", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Factor"), "2");
    await user.type(
      within(dialog).getByLabelText("Starts (optional)"),
      "2026-09-01T00:00",
    );
    await user.type(
      within(dialog).getByLabelText("Ends (optional)"),
      "2026-08-01T00:00",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Create multiplier" }),
    );

    expect(
      await screen.findByText("Start must be strictly before end."),
    ).toBeInTheDocument();
    expect(createMultiplierAction).not.toHaveBeenCalled();
  });

  it("Verify cashback rules are not offered in the rule picker", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, [
      makeRule({}),
      makeRule({
        id: "rule-2",
        name: "Cashback promo",
        reward_type: "cashback",
        reward_currency: "ZAR",
      }),
    ]);

    await user.click(within(dialog).getByRole("combobox", { name: "Rule scope" }));

    expect(
      await screen.findByRole("option", { name: "First fund bonus" }),
    ).toBeInTheDocument();
    // Multipliers never apply to cashback — the picker must hide those rules.
    expect(screen.queryByRole("option", { name: "Cashback promo" })).toBeNull();
  });

  it("Verify a backend rejection shows the reason and keeps the form open", async () => {
    createMultiplierAction.mockResolvedValue({
      ok: false,
      errorCode: "rule_not_found",
      message: "That rule does not exist in this tenant.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Factor"), "3");
    await user.click(
      within(dialog).getByRole("button", { name: "Create multiplier" }),
    );

    expect(
      await screen.findByText(/That rule does not exist in this tenant\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
