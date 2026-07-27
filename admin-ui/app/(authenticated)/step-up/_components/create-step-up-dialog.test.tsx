/**
 * Regression + behaviour tests for CreateStepUpDialog.
 *
 * The motivating bug (see commit 845c40e): editing a live step-up policy whose
 * transaction_type is a NON-p2p guarded type (cash_in / cashout / …) used to
 * collapse the type back to p2p, so the proposed update scope-mismatched. These
 * tests lock in that the dialog SEEDS the policy's real type and submits it
 * unchanged, and that the create path derives currency per transaction type.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateStepUpDialog } from "@/app/(authenticated)/step-up/_components/create-step-up-dialog";
import type { StepUpPolicy } from "@/lib/api-types";

// Mock the server actions — the dialog is unit-tested for the payload it hands
// the maker-checker pipeline, not the pipeline itself.
const proposeStepUpUpdateAction = vi.fn().mockResolvedValue({ ok: true });
const proposeStepUpChangeAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/step-up/_actions", () => ({
  proposeStepUpUpdateAction: (...args: unknown[]) => proposeStepUpUpdateAction(...args),
  proposeStepUpChangeAction: (...args: unknown[]) => proposeStepUpChangeAction(...args),
}));

const reviseAndResubmitConfigRequestAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  reviseAndResubmitConfigRequestAction: (...args: unknown[]) =>
    reviseAndResubmitConfigRequestAction(...args),
}));

/** A live cash_in step-up policy — the exact non-p2p case the bug hit. */
const cashInPolicy: StepUpPolicy = {
  id: "policy-cash-in",
  tenant_id: "tenant-1",
  transaction_type: "cash_in",
  currency: "ZAR",
  threshold_amount: "500",
  created_at: "2026-07-25T00:00:00Z",
  updated_at: "2026-07-25T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Step-up PIN policy form", () => {
  it("Verify editing a policy keeps its own service instead of resetting it", async () => {
    const user = userEvent.setup();
    render(<CreateStepUpDialog tenantId="tenant-1" open editPolicy={cashInPolicy} />);

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeStepUpUpdateAction).toHaveBeenCalledTimes(1));
    const [tenantId, targetId, payload] = proposeStepUpUpdateAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(targetId).toBe("policy-cash-in");
    expect(payload).toMatchObject({
      transaction_type: "cash_in",
      currency: "ZAR",
      threshold_amount: "500",
    });
  });

  it("Verify a money transfer policy defaults to Rand (ZAR)", async () => {
    const user = userEvent.setup();
    render(<CreateStepUpDialog tenantId="tenant-1" open />);

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeStepUpChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeStepUpChangeAction.mock.calls[0][0]).toMatchObject({
      transaction_type: "p2p",
      currency: "ZAR",
    });
  });

  it("Verify a rewards redemption policy uses points, not currency", async () => {
    const user = userEvent.setup();
    render(<CreateStepUpDialog tenantId="tenant-1" open />);

    // Open the transaction-type select and pick redemption; the currency effect
    // should switch ZAR -> PTS.
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Redemption (points)" }));
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeStepUpChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeStepUpChangeAction.mock.calls[0][0]).toMatchObject({
      transaction_type: "redemption",
      currency: "PTS",
    });
  });
});
