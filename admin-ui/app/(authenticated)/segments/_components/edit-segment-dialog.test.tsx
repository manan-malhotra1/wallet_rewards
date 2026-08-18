/**
 * Interaction tests for <EditSegmentDialog> — the PATCH /segments/{id} form
 * (Segmentation Phase 1 Task 11 fix round).
 *
 * These focus on the diff-only payload contract (only changed fields are
 * sent), the dynamic<->static conversion flows, and the is_system group-move
 * guard — the parts of this dialog that aren't already covered by
 * create-segment-dialog.test.tsx's criteria-builder/preview assertions.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditSegmentDialog } from "@/app/(authenticated)/segments/_components/edit-segment-dialog";
import type { Segment, SegmentGroup, SegmentMetricInfo, Service } from "@/lib/api-types";

const updateSegmentAction = vi.fn();
const previewCriteriaAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  updateSegmentAction: (...args: unknown[]) => updateSegmentAction(...args),
  previewCriteriaAction: (...args: unknown[]) => previewCriteriaAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const GROUPS: SegmentGroup[] = [
  {
    id: "group-1",
    tenant_id: "tenant-1",
    name: "Loyalty",
    description: null,
    is_system: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
  {
    id: "group-2",
    tenant_id: "tenant-1",
    name: "Value",
    description: null,
    is_system: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
];

const METRICS: SegmentMetricInfo[] = [
  { name: "txn_sum", supports_txn_type: true, supports_window: true },
];

const SERVICES: Service[] = [
  {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P transfer",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
];

function makeSegment(overrides: Partial<Segment>): Segment {
  return {
    id: "seg-1",
    tenant_id: "tenant-1",
    name: "VIP",
    description: "Top spenders.",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    group_id: "group-1",
    priority: 3,
    criteria: null,
    is_system: false,
    last_evaluated_at: null,
    ...overrides,
  };
}

const STATIC_SEGMENT = makeSegment({});
const DYNAMIC_SEGMENT = makeSegment({
  id: "seg-dynamic",
  name: "Big spenders",
  criteria: { v: 1, op: "AND", conditions: [{ metric: "txn_sum", gte: 5000 }] },
});
const SYSTEM_SEGMENT = makeSegment({ id: "seg-system", name: "Gold", is_system: true });

beforeEach(() => {
  vi.clearAllMocks();
  updateSegmentAction.mockResolvedValue({ ok: true });
});

async function openDialog(user: ReturnType<typeof userEvent.setup>, segment: Segment) {
  render(
    <EditSegmentDialog
      segment={segment}
      tenantId="tenant-1"
      groups={GROUPS}
      metrics={METRICS}
      services={SERVICES}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Edit segment" }));
  return screen.findByRole("dialog");
}

describe("Editing a segment — criteria, priority, move, clear", () => {
  it("Verify a dynamic segment's existing criteria is prefilled when the dialog opens", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, DYNAMIC_SEGMENT);

    expect(within(dialog).getByLabelText("Condition 1 minimum")).toHaveValue(5000);
    expect(within(dialog).getByText("txn_sum ≥ 5000")).toBeInTheDocument();
  });

  it("Verify only the changed field is sent — a priority-only edit never resends description/group_id", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    const priorityInput = within(dialog).getByLabelText("Priority");
    await user.clear(priorityInput);
    await user.type(priorityInput, "7");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateSegmentAction).toHaveBeenCalledTimes(1));
    expect(updateSegmentAction).toHaveBeenCalledWith("seg-1", "tenant-1", { priority: 7 });
  });

  it("Verify a name-only edit sends only the name field, even for an is_system segment", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, SYSTEM_SEGMENT);

    const nameInput = within(dialog).getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Platinum");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateSegmentAction).toHaveBeenCalledTimes(1));
    expect(updateSegmentAction).toHaveBeenCalledWith("seg-system", "tenant-1", {
      name: "Platinum",
    });
  });

  it("Verify clearing the name blocks submit with a local validation error", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    const nameInput = within(dialog).getByLabelText("Name");
    await user.clear(nameInput);
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(await within(dialog).findByText("Name is required.")).toBeInTheDocument();
    expect(updateSegmentAction).not.toHaveBeenCalled();
  });

  it("Verify converting a dynamic segment to static sends clear_criteria without a criteria payload", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, DYNAMIC_SEGMENT);

    await user.click(within(dialog).getByLabelText("Convert to static (clear criteria)"));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateSegmentAction).toHaveBeenCalledTimes(1));
    expect(updateSegmentAction).toHaveBeenCalledWith("seg-dynamic", "tenant-1", {
      clear_criteria: true,
    });
  });

  it("Verify adding criteria to a static segment sends the new criteria document", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    await user.click(within(dialog).getByLabelText("Dynamic segment (criteria-based)"));
    await user.click(within(dialog).getByRole("button", { name: "Add condition" }));
    await user.type(within(dialog).getByLabelText("Condition 1 minimum"), "1000");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateSegmentAction).toHaveBeenCalledTimes(1));
    expect(updateSegmentAction).toHaveBeenCalledWith("seg-1", "tenant-1", {
      criteria: { v: 1, op: "AND", conditions: [{ metric: "txn_sum", gte: 1000 }] },
    });
  });

  it("Verify the group Select is disabled for an is_system segment, with an explanatory hint", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, SYSTEM_SEGMENT);

    expect(within(dialog).getByRole("combobox", { name: "Group" })).toBeDisabled();
    expect(
      within(dialog).getByText(/System segments stay in their seeded group/),
    ).toBeInTheDocument();
  });

  it("Verify invalid criteria blocks submit instead of sending a broken payload", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    await user.click(within(dialog).getByLabelText("Dynamic segment (criteria-based)"));
    // No condition added — validateCriteria rejects an empty document.
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    // The same message renders twice on submit: once as the criteria
    // builder's own live status footer, once in the "Couldn't update" error
    // banner this component adds — assert the banner specifically, since
    // that's the behaviour under test (submit blocked + surfaced), not just
    // "the string appears somewhere."
    expect(await within(dialog).findByText("Couldn't update")).toBeInTheDocument();
    expect(within(dialog).getAllByText("Add at least one condition.").length).toBeGreaterThan(0);
    expect(updateSegmentAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected update shows the backend's reason and keeps the dialog open", async () => {
    updateSegmentAction.mockResolvedValue({
      ok: false,
      errorCode: "segment_protected",
      message: "System segments cannot change group.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    const priorityInput = within(dialog).getByLabelText("Priority");
    await user.clear(priorityInput);
    await user.type(priorityInput, "9");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await within(dialog).findByText(/System segments cannot change group\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Verify submitting with no actual changes is blocked locally, never round-tripping a no-op PATCH", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, STATIC_SEGMENT);

    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(await within(dialog).findByText("No changes to save.")).toBeInTheDocument();
    expect(updateSegmentAction).not.toHaveBeenCalled();
  });
});
