/**
 * Interaction tests for LimitChangesRequested — the "Open requests" section on
 * the Limits page, from the admin's point of view.
 *
 * Drives the maker's withdraw control (confirm dialog + server action) and
 * asserts the maker-only "Edit & resubmit" affordance appears for a returned
 * change — covering both limit config types (spending limit vs wallet balance
 * limit), which route to different revise dialogs. Both dialogs are stubbed to
 * their trigger; server actions are mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LimitChangesRequested } from "@/app/(authenticated)/limits/_components/limit-changes-requested";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest, Instrument, Service } from "@/lib/api-types";

vi.mock("./create-limit-dialog", () => ({
  CreateLimitDialog: (props: { trigger?: React.ReactNode }) => <>{props.trigger}</>,
}));
vi.mock("./create-wallet-limit-dialog", () => ({
  CreateWalletLimitDialog: (props: { trigger?: React.ReactNode }) => <>{props.trigger}</>,
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
    code: "cashout",
    display_name: "Cash-out",
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
const instruments: Instrument[] = [
  {
    id: "inst-1",
    tenant_id: "tenant-1",
    code: "ZAR",
    symbol: "R",
    display_name: "Rand",
    description: null,
    account_type: "financial_wallet",
    status: "active",
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  },
];

function makeRequest(overrides: Partial<ConfigChangeRequest> = {}): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "limit",
    operation: "create",
    payload: { transaction_type: "cashout", user_type: "consumer", currency: "ZAR" },
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
      <LimitChangesRequested
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

describe("Limit change open requests", () => {
  it("Verify the maker can withdraw a pending limit change", async () => {
    const user = userEvent.setup();
    renderSection(makeRequest(), MAKER);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() =>
      expect(withdrawConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
  });

  it("Verify the maker can reopen a returned spending limit to edit it", () => {
    renderSection(
      makeRequest({ config_type: "limit", status: "CHANGES_REQUESTED" }),
      MAKER,
    );

    expect(
      screen.getByRole("button", { name: /Edit & resubmit/ }),
    ).toBeInTheDocument();
  });

  it("Verify the maker can reopen a returned wallet balance limit to edit it", () => {
    renderSection(
      makeRequest({
        config_type: "wallet_limit",
        status: "CHANGES_REQUESTED",
        payload: { user_type: "consumer", currency: "ZAR" },
      }),
      MAKER,
    );

    expect(
      screen.getByRole("button", { name: /Edit & resubmit/ }),
    ).toBeInTheDocument();
  });
});
