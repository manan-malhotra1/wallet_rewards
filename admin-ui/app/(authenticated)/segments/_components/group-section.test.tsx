/**
 * Interaction tests for <GroupSection> — the priority-ordered segment table
 * inside one collapsible group, plus its confirm-guarded group delete.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GroupSection } from "@/app/(authenticated)/segments/_components/group-section";
import type { Segment, SegmentGroup } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/utils";

const deleteSegmentGroupAction = vi.fn();
const addUserToSegmentAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  deleteSegmentGroupAction: (...args: unknown[]) => deleteSegmentGroupAction(...args),
  addUserToSegmentAction: (...args: unknown[]) => addUserToSegmentAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const GROUP: SegmentGroup = {
  id: "group-1",
  tenant_id: "tenant-1",
  name: "Loyalty",
  description: "Tenure-based loyalty tiers.",
  is_system: false,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const SYSTEM_GROUP: SegmentGroup = { ...GROUP, id: "group-sys", is_system: true };

function makeSegment(overrides: Partial<Segment>): Segment {
  return {
    id: "seg-1",
    tenant_id: "tenant-1",
    name: "Segment",
    description: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    group_id: "group-1",
    priority: 0,
    criteria: null,
    is_system: false,
    last_evaluated_at: null,
    ...overrides,
  };
}

const BRONZE = makeSegment({ id: "seg-bronze", name: "Bronze", priority: 1, is_system: true });
const GOLD = makeSegment({ id: "seg-gold", name: "Gold", priority: 10, is_system: true });
// Equal priority (5) on purpose — exercises the name-ASC tiebreak in
// `byPriorityDesc` rather than the priority comparison itself.
const TIE_ALPHA = makeSegment({ id: "seg-alpha", name: "Alpha", priority: 5 });
const TIE_ZETA = makeSegment({ id: "seg-zeta", name: "Zeta", priority: 5 });
const DYNAMIC_PENDING = makeSegment({
  id: "seg-dynamic",
  name: "Big spenders",
  priority: 5,
  criteria: { v: 1, op: "AND", conditions: [{ metric: "txn_sum", gte: 5000 }] },
  last_evaluated_at: null,
});
const DYNAMIC_EVALUATED = makeSegment({
  id: "seg-dynamic-2",
  name: "Frequent senders",
  priority: 7,
  criteria: { v: 1, op: "AND", conditions: [{ metric: "txn_count", gte: 3 }] },
  last_evaluated_at: "2026-08-10T12:00:00Z",
});

beforeEach(() => {
  vi.clearAllMocks();
  deleteSegmentGroupAction.mockResolvedValue({ ok: true });
  addUserToSegmentAction.mockResolvedValue({ ok: true });
});

describe("Group-sectioned segments — one group's table", () => {
  it("Verify segments render priority-DESC, highest priority first", () => {
    render(
      <GroupSection group={GROUP} segments={[BRONZE, GOLD]} tenantId="tenant-1" />,
    );

    const rows = screen.getAllByRole("row").filter((r) => within(r).queryByText(/Gold|Bronze/));
    expect(within(rows[0]).getByText("Gold")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Bronze")).toBeInTheDocument();
  });

  it("Verify equal-priority segments break the tie alphabetically by name", () => {
    // Passed in Zeta-then-Alpha order so a passing test can only mean the
    // component itself re-sorted them, not that they happened to already be
    // in the right order.
    render(
      <GroupSection group={GROUP} segments={[TIE_ZETA, TIE_ALPHA]} tenantId="tenant-1" />,
    );

    const rows = screen.getAllByRole("row").filter((r) => within(r).queryByText(/Alpha|Zeta/));
    expect(within(rows[0]).getByText("Alpha")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Zeta")).toBeInTheDocument();
  });

  it("Verify a dynamic segment shows a Dynamic badge and a static one shows Static", () => {
    render(
      <GroupSection group={GROUP} segments={[BRONZE, DYNAMIC_PENDING]} tenantId="tenant-1" />,
    );

    expect(screen.getByText("Static")).toBeInTheDocument();
    expect(screen.getByText("Dynamic")).toBeInTheDocument();
  });

  it("Verify a dynamic segment's criteria summary renders in the Criteria column", () => {
    render(<GroupSection group={GROUP} segments={[DYNAMIC_PENDING]} tenantId="tenant-1" />);

    expect(screen.getByText("txn_sum ≥ 5000")).toBeInTheDocument();
  });

  it("Verify a dynamic segment with a null last_evaluated_at shows Pending recompute", () => {
    render(<GroupSection group={GROUP} segments={[DYNAMIC_PENDING]} tenantId="tenant-1" />);

    expect(screen.getByText("Pending recompute")).toBeInTheDocument();
  });

  it("Verify an evaluated dynamic segment shows its formatted last-evaluated timestamp, not Pending", () => {
    render(<GroupSection group={GROUP} segments={[DYNAMIC_EVALUATED]} tenantId="tenant-1" />);

    expect(screen.queryByText("Pending recompute")).not.toBeInTheDocument();
    // Assert the actual rendered text, not just the absence of "Pending" —
    // pins the cell to `formatTimestamp`'s output rather than any string
    // that happens not to say "Pending recompute".
    expect(
      screen.getByText(formatTimestamp(DYNAMIC_EVALUATED.last_evaluated_at!)),
    ).toBeInTheDocument();
  });

  it("Verify the delete-group button is hidden for a system group", () => {
    render(<GroupSection group={SYSTEM_GROUP} segments={[BRONZE]} tenantId="tenant-1" />);

    expect(screen.queryByRole("button", { name: "Delete group" })).not.toBeInTheDocument();
    // Two "System" badges are expected here: the group header's own badge
    // (system group) plus Bronze's (a system-seeded segment) — just assert
    // at least one renders rather than pinning an exact count.
    expect(screen.getAllByText("System").length).toBeGreaterThan(0);
  });

  it("Verify the delete-group button is hidden when canDelete is false, even for a non-system group", () => {
    render(
      <GroupSection group={GROUP} segments={[BRONZE]} tenantId="tenant-1" canDelete={false} />,
    );

    expect(screen.queryByRole("button", { name: "Delete group" })).not.toBeInTheDocument();
  });

  it("Verify confirming group delete calls the action with (group.id, tenantId)", async () => {
    const user = userEvent.setup();
    render(<GroupSection group={GROUP} segments={[BRONZE]} tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Delete group" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteSegmentGroupAction).toHaveBeenCalledTimes(1));
    expect(deleteSegmentGroupAction).toHaveBeenCalledWith("group-1", "tenant-1");
  });

  it("Verify a failed group delete surfaces the backend message in a danger toast", async () => {
    deleteSegmentGroupAction.mockResolvedValue({
      ok: false,
      errorCode: "segment_group_not_empty",
      message: "Move or delete its segments first.",
    });
    const user = userEvent.setup();
    render(<GroupSection group={GROUP} segments={[BRONZE]} tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Delete group" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Couldn't delete",
          description: "segment_group_not_empty: Move or delete its segments first.",
          variant: "danger",
        }),
      ),
    );
  });

  it("Verify the assign-user affordance only appears on static segment rows", () => {
    render(
      <GroupSection group={GROUP} segments={[BRONZE, DYNAMIC_PENDING]} tenantId="tenant-1" />,
    );

    // One static segment -> exactly one assign-user button.
    expect(screen.getAllByRole("button", { name: "Assign user" })).toHaveLength(1);
  });

  it("Verify a failed assign keeps the user-id row open with the typed value intact", async () => {
    addUserToSegmentAction.mockResolvedValue({
      ok: false,
      errorCode: "user_not_found",
      message: "No such user.",
    });
    const user = userEvent.setup();
    render(<GroupSection group={GROUP} segments={[BRONZE]} tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: "Assign user" }));
    await user.type(screen.getByPlaceholderText("00000000-…"), "not-a-real-id");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Couldn't add", variant: "danger" }),
      ),
    );
    // The prompt row (and what the admin typed) is still there to fix and retry.
    expect(screen.getByPlaceholderText("00000000-…")).toHaveValue("not-a-real-id");
  });

  it("Verify the collapsible header points aria-controls at the body it toggles", () => {
    render(<GroupSection group={GROUP} segments={[BRONZE]} tenantId="tenant-1" />);

    const toggle = screen.getByRole("button", { name: /Loyalty/ });
    const controlsId = toggle.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId!)).not.toBeNull();
  });
});
