/**
 * Interaction tests for CommissionChangesRequested — the "Open requests"
 * section on the Commission page, from the admin's point of view.
 *
 * Every viewer sees an in-flight proposal and can open it read-only; the
 * mutating affordances (Withdraw, Edit & resubmit) are gated to the maker on a
 * non-terminal request. These drive the withdraw control (confirm dialog +
 * server action) and assert the maker-only edit affordance appears for a
 * returned change but not for a colleague. The create dialog is stubbed to its
 * trigger; server actions are mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommissionChangesRequested } from "@/app/(authenticated)/commissions/_components/commission-changes-requested";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";

// Stub the revise dialog down to whatever trigger it is handed.
vi.mock("./create-commission-dialog", () => ({
  CreateCommissionDialog: (props: { trigger?: React.ReactNode }) => <>{props.trigger}</>,
}));

// Mock the config-request actions the card calls (withdraw + lazy detail load).
const withdrawConfigRequestAction = vi.fn();
const loadConfigRequestAction = vi.fn();
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  withdrawConfigRequestAction: (...args: unknown[]) => withdrawConfigRequestAction(...args),
  loadConfigRequestAction: (...args: unknown[]) => loadConfigRequestAction(...args),
  approveConfigRequestAction: vi.fn(),
  requestConfigChangesAction: vi.fn(),
  loadConfigHistoryAction: vi.fn(),
}));

const MAKER = "admin-maker";

const services: Service[] = [
  {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "Peer-to-Peer",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  },
];
const instruments: Instrument[] = [];

function makeRequest(overrides: Partial<ConfigChangeRequest> = {}): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "commission",
    operation: "create",
    payload: { transaction_type: "p2p", user_type: "agent", currency: "ZAR" },
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
      <CommissionChangesRequested
        requests={[request]}
        tenantId="tenant-1"
        currentAdminId={currentAdminId}
        services={services}
        instruments={instruments}
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  withdrawConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Commission open requests", () => {
  it("Verify the maker can withdraw a pending commission change", async () => {
    const user = userEvent.setup();
    renderSection(makeRequest(), MAKER);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() =>
      expect(withdrawConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
  });

  it("Verify a colleague can see a commission change but cannot withdraw it", () => {
    renderSection(makeRequest({ status: "CHANGES_REQUESTED" }), "someone-else");

    // The read-only View affordance is always present...
    expect(
      screen.getByRole("button", { name: "View request details" }),
    ).toBeInTheDocument();
    // ...but a non-maker gets neither Withdraw nor Edit.
    expect(screen.queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit & resubmit/ }),
    ).not.toBeInTheDocument();
  });

  it("Verify the maker can reopen a returned commission change to edit it", () => {
    renderSection(makeRequest({ status: "CHANGES_REQUESTED" }), MAKER);

    expect(
      screen.getByRole("button", { name: /Edit & resubmit/ }),
    ).toBeInTheDocument();
  });
});
