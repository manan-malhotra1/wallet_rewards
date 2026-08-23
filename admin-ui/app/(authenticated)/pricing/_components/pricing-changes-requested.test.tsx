/**
 * Interaction tests for PricingChangesRequested — the "Open requests" section
 * on the Service charges page, from the admin's point of view.
 *
 * Drives the maker's withdraw control (confirm dialog + server action) and
 * asserts the maker-only "Edit & resubmit" affordance appears for a returned
 * fee change. The revise dialog is stubbed to its trigger; server actions are
 * mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PricingChangesRequested } from "@/app/(authenticated)/pricing/_components/pricing-changes-requested";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

vi.mock("./create-pricing-dialog", () => ({
  CreatePricingDialog: (props: { trigger?: React.ReactNode }) => <>{props.trigger}</>,
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
    readiness: null,
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
    config_type: "pricing",
    operation: "create",
    payload: { transaction_type: "p2p", user_type: "consumer", currency: "ZAR" },
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
      <PricingChangesRequested
      pointsAvailable
        requests={[request]}
        tenantId="tenant-1"
        currentAdminId={currentAdminId}
        services={services}
        instruments={instruments}
        catalog={SEED_USER_TYPE_CATALOG}
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  withdrawConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("Fee change open requests", () => {
  it("Verify the maker can withdraw a pending fee change", async () => {
    const user = userEvent.setup();
    renderSection(makeRequest(), MAKER);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() =>
      expect(withdrawConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
  });

  it("Verify the maker can reopen a returned fee change to edit it", () => {
    renderSection(makeRequest({ status: "CHANGES_REQUESTED" }), MAKER);

    expect(
      screen.getByRole("button", { name: /Edit & resubmit/ }),
    ).toBeInTheDocument();
  });
});
