/**
 * Interaction tests for MoneyOperationDetailDrawer — the treasury maker-checker
 * surface, driven from the approver's (and the maker's) point of view.
 *
 * These exercise real user actions through the drawer footer: a second admin
 * approving a pending move (behind its confirm step), a checker being forced to
 * leave a comment when requesting changes, a backend rejection surfacing its
 * reason, and the maker's own withdraw + revise-and-resubmit flows. The server
 * actions are mocked — the drawer is tested for the calls it makes and the UI
 * it shows, not the pipeline behind them.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MoneyOperationDetailDrawer } from "@/app/(authenticated)/money-operations/_components/money-operation-detail-drawer";
import type { MoneyOperation } from "@/lib/api-types";

// Mock the treasury review verbs; each resolves to the updated operation.
const approveMoneyOperationAction = vi.fn();
const requestMoneyOpChangesAction = vi.fn();
const reviseAndResubmitMoneyOperationAction = vi.fn();
const withdrawMoneyOperationAction = vi.fn();
vi.mock("@/app/(authenticated)/money-operations/_actions", () => ({
  approveMoneyOperationAction: (...args: unknown[]) => approveMoneyOperationAction(...args),
  requestMoneyOpChangesAction: (...args: unknown[]) => requestMoneyOpChangesAction(...args),
  reviseAndResubmitMoneyOperationAction: (...args: unknown[]) =>
    reviseAndResubmitMoneyOperationAction(...args),
  withdrawMoneyOperationAction: (...args: unknown[]) => withdrawMoneyOperationAction(...args),
}));

const MAKER = "admin-maker";
const CHECKER = "admin-checker";

/** A pending fund-user treasury move, maker = MAKER. */
function makeOperation(overrides: Partial<MoneyOperation> = {}): MoneyOperation {
  return {
    id: "mo-1",
    tenant_id: "tenant-1",
    operation: "fund_user",
    payload: {
      identifier_type: "phone",
      identifier_value: "+27825550142",
      amount: "100",
      currency: "ZAR",
      reason: "Top-up",
    },
    status: "PENDING",
    maker_admin_id: MAKER,
    maker_admin_name: "Mandla Maker",
    required_approvals: 2,
    approvals_count: 1,
    applied_transaction_id: null,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    subject_name: "Thandi User",
    account_name: null,
    bank_mirror_name: null,
    ...overrides,
  };
}

function renderDrawer(
  operation: MoneyOperation,
  currentAdminId: string,
  canApprove: boolean,
) {
  const onUpdated = vi.fn();
  render(
    <MoneyOperationDetailDrawer
      operation={operation}
      tenantId="tenant-1"
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
  approveMoneyOperationAction.mockResolvedValue({ ok: true, operation: makeOperation() });
  requestMoneyOpChangesAction.mockResolvedValue({ ok: true, operation: makeOperation() });
  reviseAndResubmitMoneyOperationAction.mockResolvedValue({
    ok: true,
    operation: makeOperation(),
  });
  withdrawMoneyOperationAction.mockResolvedValue({ ok: true, operation: makeOperation() });
});

describe("Treasury move approval drawer", () => {
  it("Verify a second admin can approve a pending treasury move", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeOperation(), CHECKER, true);

    // Approve is behind an explicit confirm step (it moves money).
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approve" }));

    await waitFor(() =>
      expect(approveMoneyOperationAction).toHaveBeenCalledWith("tenant-1", "mo-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("Verify requesting changes on a treasury move needs a comment", async () => {
    const user = userEvent.setup();
    renderDrawer(makeOperation(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Request changes" }));
    // Submitting with an empty comment is blocked and never calls the action.
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    expect(requestMoneyOpChangesAction).not.toHaveBeenCalled();
    expect(
      screen.getByText("A comment is required when requesting changes."),
    ).toBeInTheDocument();

    // With a comment it goes through, carrying the trimmed text.
    await user.type(screen.getByLabelText("Comment (required)"), "Amount looks too high");
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    await waitFor(() =>
      expect(requestMoneyOpChangesAction).toHaveBeenCalledWith(
        "tenant-1",
        "mo-1",
        "Amount looks too high",
      ),
    );
  });

  it("Verify a rejected approval attempt shows the reason", async () => {
    approveMoneyOperationAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "maker_checker_self_approval",
      message: "You proposed this move.",
    });
    const user = userEvent.setup();
    renderDrawer(makeOperation(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approve" }));

    expect(
      await screen.findByText("maker_checker_self_approval: You proposed this move."),
    ).toBeInTheDocument();
  });

  it("Verify the maker can withdraw their own pending treasury move", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeOperation(), MAKER, false);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));
    await user.click(screen.getByRole("button", { name: "Confirm withdraw" }));

    await waitFor(() =>
      expect(withdrawMoneyOperationAction).toHaveBeenCalledWith("tenant-1", "mo-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("Verify the maker can revise and resubmit a returned treasury move", async () => {
    const user = userEvent.setup();
    renderDrawer(makeOperation({ status: "CHANGES_REQUESTED" }), MAKER, false);

    // First "Revise & resubmit" opens the JSON editor; the second submits it.
    await user.click(screen.getByRole("button", { name: "Revise & resubmit" }));
    await user.click(screen.getByRole("button", { name: "Revise & resubmit" }));

    await waitFor(() =>
      expect(reviseAndResubmitMoneyOperationAction).toHaveBeenCalledWith(
        "tenant-1",
        "mo-1",
        expect.objectContaining({ amount: "100", currency: "ZAR" }),
      ),
    );
  });
});
