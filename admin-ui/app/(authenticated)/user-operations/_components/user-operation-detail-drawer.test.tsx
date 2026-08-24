/**
 * Interaction tests for UserOperationDetailDrawer — the create/edit-user
 * maker-checker surface, driven from the approver's (and the maker's) point of
 * view.
 *
 * These exercise real user actions through the drawer footer: a second admin
 * approving a pending user change (behind its confirm step), a checker being
 * forced to leave a comment when requesting changes, a backend rejection
 * surfacing its reason, and the maker's own withdraw + revise-and-resubmit
 * flows. Server actions are mocked — the drawer is tested for the calls it
 * makes and the UI it shows.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserOperationDetailDrawer } from "@/app/(authenticated)/user-operations/_components/user-operation-detail-drawer";
import type { UserOperation } from "@/lib/api-types";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

// Mock the user-operation review verbs; each resolves to the updated operation.
const approveUserOperationAction = vi.fn();
const requestUserOpChangesAction = vi.fn();
const reviseAndResubmitUserOperationAction = vi.fn();
const withdrawUserOperationAction = vi.fn();
vi.mock("@/app/(authenticated)/user-operations/_actions", () => ({
  approveUserOperationAction: (...args: unknown[]) => approveUserOperationAction(...args),
  requestUserOpChangesAction: (...args: unknown[]) => requestUserOpChangesAction(...args),
  reviseAndResubmitUserOperationAction: (...args: unknown[]) =>
    reviseAndResubmitUserOperationAction(...args),
  withdrawUserOperationAction: (...args: unknown[]) => withdrawUserOperationAction(...args),
}));

const MAKER = "admin-maker";
const CHECKER = "admin-checker";

/** A pending create-user request, maker = MAKER. */
function makeOperation(overrides: Partial<UserOperation> = {}): UserOperation {
  return {
    id: "uo-1",
    tenant_id: "tenant-1",
    operation: "create_user",
    payload: {
      user_type: "consumer",
      profile: { first_name: "Thandi", last_name: "Nkosi" },
      identifiers: [{ identifier_type: "phone", identifier_value: "+27825550142" }],
    },
    status: "PENDING",
    maker_admin_id: MAKER,
    maker_admin_name: "Mandla Maker",
    required_approvals: 2,
    approvals_count: 1,
    applied_user_id: null,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    target_name: null,
    ...overrides,
  };
}

function renderDrawer(
  operation: UserOperation,
  currentAdminId: string,
  canApprove: boolean,
) {
  const onUpdated = vi.fn();
  render(
    <UserOperationDetailDrawer
      operation={operation}
      tenantId="tenant-1"
      catalog={SEED_USER_TYPE_CATALOG}
      canApprove={canApprove}
      currentAdminId={currentAdminId}
      open
      onOpenChange={vi.fn()}
      onUpdated={onUpdated}
    />,
  );
  return { onUpdated };
}

beforeEach(() => {
  vi.clearAllMocks();
  approveUserOperationAction.mockResolvedValue({ ok: true, operation: makeOperation() });
  requestUserOpChangesAction.mockResolvedValue({ ok: true, operation: makeOperation() });
  reviseAndResubmitUserOperationAction.mockResolvedValue({
    ok: true,
    operation: makeOperation(),
  });
  withdrawUserOperationAction.mockResolvedValue({ ok: true, operation: makeOperation() });
});

describe("User change approval drawer", () => {
  it("Verify a second admin can approve a pending user change", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeOperation(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approve" }));

    await waitFor(() =>
      expect(approveUserOperationAction).toHaveBeenCalledWith("tenant-1", "uo-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("Verify requesting changes on a user change needs a comment", async () => {
    const user = userEvent.setup();
    renderDrawer(makeOperation(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Request changes" }));
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    expect(requestUserOpChangesAction).not.toHaveBeenCalled();
    expect(
      screen.getByText("A comment is required when requesting changes."),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Comment (required)"), "Fix the surname");
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    await waitFor(() =>
      expect(requestUserOpChangesAction).toHaveBeenCalledWith(
        "tenant-1",
        "uo-1",
        "Fix the surname",
      ),
    );
  });

  it("Verify a rejected approval attempt on a user change shows the reason", async () => {
    approveUserOperationAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "maker_checker_self_approval",
      message: "You proposed this change.",
    });
    const user = userEvent.setup();
    renderDrawer(makeOperation(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approve" }));

    expect(
      await screen.findByText("maker_checker_self_approval: You proposed this change."),
    ).toBeInTheDocument();
  });

  it("Verify the maker can withdraw their own pending user change", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeOperation(), MAKER, false);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    await user.click(screen.getByRole("button", { name: "Confirm withdraw" }));

    await waitFor(() =>
      expect(withdrawUserOperationAction).toHaveBeenCalledWith("tenant-1", "uo-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("Verify the maker can revise and resubmit a returned user change", async () => {
    const user = userEvent.setup();
    renderDrawer(makeOperation({ status: "CHANGES_REQUESTED" }), MAKER, false);

    await user.click(screen.getByRole("button", { name: "Revise & resubmit" }));
    await user.click(screen.getByRole("button", { name: "Revise & resubmit" }));

    await waitFor(() =>
      expect(reviseAndResubmitUserOperationAction).toHaveBeenCalledWith(
        "tenant-1",
        "uo-1",
        expect.objectContaining({ user_type: "consumer" }),
      ),
    );
  });
});
