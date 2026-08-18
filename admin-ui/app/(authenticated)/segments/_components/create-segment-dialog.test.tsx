/**
 * Interaction tests for <CreateSegmentDialog> — the admin "New segment" form.
 *
 * These drive the dialog the way an admin does — open it, name the cohort,
 * pick a group, add an optional description, submit — and assert the
 * outcome the admin cares about: the create-segment action receives exactly
 * the payload typed (group_id + priority always included), a nameless
 * segment is refused before anything is sent, and a backend rejection is
 * shown without closing the form. The server actions are mocked; no backend
 * is touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateSegmentDialog } from "@/app/(authenticated)/segments/_components/create-segment-dialog";
import type { SegmentGroup, SegmentMetricInfo, Service } from "@/lib/api-types";

const createSegmentAction = vi.fn();
const previewCriteriaAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  createSegmentAction: (...args: unknown[]) => createSegmentAction(...args),
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

beforeEach(() => {
  vi.clearAllMocks();
  createSegmentAction.mockResolvedValue({ ok: true });
});

/** Open the dialog and return its content node. */
async function openDialog(
  user: ReturnType<typeof userEvent.setup>,
  groups: SegmentGroup[] = GROUPS,
) {
  render(
    <CreateSegmentDialog
      tenantId="tenant-1"
      groups={groups}
      metrics={METRICS}
      services={SERVICES}
      trigger={<button type="button">New segment</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New segment" }));
  return screen.findByRole("dialog");
}

describe("Managing reward segments — creating a segment", () => {
  it("Verify an admin can create a static customer segment scoped to a group", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "vip-users");
    await user.type(
      within(dialog).getByLabelText("Description (optional)"),
      "Top 1% by lifetime spend.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createSegmentAction).toHaveBeenCalledTimes(1));
    expect(createSegmentAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      group_id: "group-1",
      name: "vip-users",
      description: "Top 1% by lifetime spend.",
      priority: 0,
      criteria: undefined,
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Segment created" }),
    );
    // A successful create closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a segment cannot be created without a name", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(createSegmentAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected segment shows the reason and keeps the form open", async () => {
    createSegmentAction.mockResolvedValue({
      ok: false,
      errorCode: "segment_name_taken",
      message: "A segment with that name already exists.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "vip-users");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/A segment with that name already exists\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Verify the group picker is disabled with a hint when no groups exist", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, []);

    expect(within(dialog).getByRole("combobox", { name: "Group" })).toBeDisabled();
    expect(
      within(dialog).getByText("Create a segment group before a segment."),
    ).toBeInTheDocument();
  });

  it("Verify checking Dynamic segment mounts the criteria builder and blocks submit until valid", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "big-spenders");
    await user.click(within(dialog).getByLabelText("Dynamic segment (criteria-based)"));

    // No conditions yet — the criteria builder shows its own validation.
    expect(within(dialog).getByText("Add at least one condition.")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Create" }));
    expect(createSegmentAction).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Add condition" }));
    await user.type(within(dialog).getByLabelText("Condition 1 minimum"), "5000");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createSegmentAction).toHaveBeenCalledTimes(1));
    expect(createSegmentAction.mock.calls[0][0]).toMatchObject({
      group_id: "group-1",
      name: "big-spenders",
      criteria: { v: 1, op: "AND", conditions: [{ metric: "txn_sum", gte: 5000 }] },
    });
  });

  it("Verify Preview matches calls the preview action and shows the match count", async () => {
    previewCriteriaAction.mockResolvedValue({ ok: true, count: 42 });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByLabelText("Dynamic segment (criteria-based)"));
    await user.click(within(dialog).getByRole("button", { name: "Add condition" }));
    await user.type(within(dialog).getByLabelText("Condition 1 minimum"), "1");
    await user.click(within(dialog).getByRole("button", { name: "Preview matches" }));

    await waitFor(() => expect(previewCriteriaAction).toHaveBeenCalledTimes(1));
    expect(previewCriteriaAction).toHaveBeenCalledWith(
      "tenant-1",
      expect.objectContaining({ conditions: [{ metric: "txn_sum", gte: 1 }] }),
    );
    expect(await within(dialog).findByText("~42 users match")).toBeInTheDocument();
  });

  it("Verify an emptied priority field blocks submit instead of silently defaulting to 0", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "vip-users");
    await user.clear(within(dialog).getByLabelText("Priority"));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Priority is required.")).toBeInTheDocument();
    expect(createSegmentAction).not.toHaveBeenCalled();
  });

  it("Verify a failed preview shows its own banner and never masks a create failure", async () => {
    previewCriteriaAction.mockResolvedValue({
      ok: false,
      errorCode: "tenant_not_found",
      message: "Unknown tenant.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByLabelText("Dynamic segment (criteria-based)"));
    await user.click(within(dialog).getByRole("button", { name: "Add condition" }));
    await user.type(within(dialog).getByLabelText("Condition 1 minimum"), "1");
    await user.click(within(dialog).getByRole("button", { name: "Preview matches" }));

    expect(await within(dialog).findByText("Couldn't preview")).toBeInTheDocument();
    expect(within(dialog).getByText(/Unknown tenant\./)).toBeInTheDocument();
    // The create-submit failure banner never fired — only the preview one did.
    expect(within(dialog).queryByText("Couldn't create")).not.toBeInTheDocument();
  });
});
