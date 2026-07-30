/**
 * Interaction tests for StepUpChangesRequested — the "Open requests" section on
 * the Step-up PIN page, from the admin's point of view.
 *
 * Drives the maker's withdraw control (confirm dialog + server action) and
 * asserts the maker-only "Edit & resubmit" affordance appears for a returned
 * step-up change. The revise dialog is stubbed to its trigger; server actions
 * are mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StepUpChangesRequested } from "@/app/(authenticated)/step-up/_components/step-up-changes-requested";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest } from "@/lib/api-types";

vi.mock("./create-step-up-dialog", () => ({
  CreateStepUpDialog: (props: { trigger?: React.ReactNode }) => <>{props.trigger}</>,
}));

const withdrawConfigRequestAction = vi.fn();
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  withdrawConfigRequestAction: (...args: unknown[]) => withdrawConfigRequestAction(...args),
  loadConfigRequestAction: vi.fn(),
  approveConfigRequestAction: vi.fn(),
  requestConfigChangesAction: vi.fn(),
  loadConfigHistoryAction: vi.fn(),
}));

const MAKER = "admin-maker";

function makeRequest(overrides: Partial<ConfigChangeRequest> = {}): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "step_up",
    operation: "create",
    payload: { transaction_type: "p2p", currency: "ZAR", threshold_amount: "500" },
    target_config_id: null,
    status: "PENDING",
    maker_admin_id: MAKER,
    maker_admin_name: "Mandla Maker",
    checker_admin_id: null,
    checker_admin_name: null,
    revision: 1,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    ...overrides,
  };
}

function renderSection(request: ConfigChangeRequest, currentAdminId: string) {
  render(
    <TooltipProvider>
      <StepUpChangesRequested
        requests={[request]}
        tenantId="tenant-1"
        currentAdminId={currentAdminId}
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  withdrawConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Step-up change open requests", () => {
  it("Verify the maker can withdraw a pending PIN step-up change", async () => {
    const user = userEvent.setup();
    renderSection(makeRequest(), MAKER);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() =>
      expect(withdrawConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
  });

  it("Verify the maker can reopen a returned PIN step-up change to edit it", () => {
    renderSection(makeRequest({ status: "CHANGES_REQUESTED" }), MAKER);

    expect(
      screen.getByRole("button", { name: /Edit & resubmit/ }),
    ).toBeInTheDocument();
  });
});
