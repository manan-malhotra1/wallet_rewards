/**
 * Interaction tests for <ConfigRequestsTable> — the config change-request list
 * and its per-row "View" action, driven from an approver's chair.
 *
 * Clicking a row's View button lazily loads the full request (with its review
 * thread) via a server action, then opens the detail drawer. These tests assert
 * that wiring: the action is called with the right tenant + request id and the
 * drawer opens on success, while a failed load surfaces an error toast and
 * leaves the drawer closed. The detail drawer itself is stubbed to a marker —
 * its own review controls are covered by request-detail-drawer.test.tsx.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigRequestsTable } from "@/app/(authenticated)/config-requests/_components/config-requests-table";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest } from "@/lib/api-types";

// The row action's only side effect is a server-action fetch.
const loadConfigRequestAction = vi.fn();
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  loadConfigRequestAction: (...args: unknown[]) => loadConfigRequestAction(...args),
}));

// Capture the danger toast raised when a load fails.
const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

// The detail drawer is not under test — stub it to a marker that reflects open.
vi.mock("./request-detail-drawer", () => ({
  RequestDetailDrawer: ({ open }: { open: boolean }) =>
    open ? <div>request detail drawer</div> : null,
}));

function makeRequest(overrides: Partial<ConfigChangeRequest> = {}): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "tax",
    operation: "create",
    payload: { rate: "0.15" },
    target_config_id: null,
    status: "PENDING",
    maker_admin_id: "admin-maker",
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

function renderTable() {
  render(
    <TooltipProvider>
      <ConfigRequestsTable
        requests={[makeRequest()]}
        tenantId="tenant-1"
        canApprove
        currentAdminId="admin-checker"
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Config requests — table row actions", () => {
  it("Verify an admin can open a config request's details from the table", async () => {
    loadConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "View" }));

    // The full request is fetched for exactly this row, then the drawer opens.
    await waitFor(() =>
      expect(loadConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
    expect(await screen.findByText("request detail drawer")).toBeInTheDocument();
    expect(toast).not.toHaveBeenCalled();
  });

  it("Verify a failed request load shows an error and leaves the drawer closed", async () => {
    loadConfigRequestAction.mockResolvedValue({
      ok: false,
      errorCode: "not_found",
      message: "Request no longer exists.",
    });
    const user = userEvent.setup();
    renderTable();

    await user.click(screen.getByRole("button", { name: "View" }));

    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "danger" }),
    );
    expect(screen.queryByText("request detail drawer")).not.toBeInTheDocument();
  });
});
