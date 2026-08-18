/**
 * Interaction tests for CreatePricingDialog from the fee administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, keep the
 * defaulted scope (service / account / currency), type a band's fee and submit
 * — and assert the outcome the admin cares about: a pricing schedule is
 * PROPOSED through the maker-checker pipeline with exactly the band they
 * entered, an invalid band is refused before anything is sent, and a backend
 * rejection is surfaced verbatim. The route's server actions are mocked; no
 * backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreatePricingDialog } from "@/app/(authenticated)/pricing/_components/create-pricing-dialog";
import type { Instrument, Service } from "@/lib/api-types";

const proposePricingBandsAction = vi.fn().mockResolvedValue({ ok: true });
const proposePricingUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/pricing/_actions", () => ({
  proposePricingBandsAction: (...args: unknown[]) => proposePricingBandsAction(...args),
  proposePricingUpdateAction: (...args: unknown[]) => proposePricingUpdateAction(...args),
}));

const reviseAndResubmitConfigRequestAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  reviseAndResubmitConfigRequestAction: (...args: unknown[]) =>
    reviseAndResubmitConfigRequestAction(...args),
}));

const services = [
  {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "Send money",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    readiness: null,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
] satisfies Service[];

const instruments = [
  {
    id: "inst-1",
    tenant_id: "tenant-1",
    code: "ZAR",
    symbol: "R",
    display_name: "Rand",
    description: null,
    account_type: "financial_wallet",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
] satisfies Instrument[];

/** Render the dialog behind a trigger, open it, and return the userEvent instance. */
async function openDialog() {
  const user = userEvent.setup();
  render(
    <CreatePricingDialog
      pointsAvailable
      tenantId="tenant-1"
      services={services}
      instruments={instruments}
      trigger={<button type="button">New pricing</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New pricing" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Propose a pricing schedule", () => {
  it("Verify an admin can propose a new fee for a service", async () => {
    const user = await openDialog();

    const fixed = screen.getByLabelText("Fixed");
    await user.clear(fixed);
    await user.type(fixed, "5");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposePricingBandsAction).toHaveBeenCalledTimes(1));
    const [tenantId, payload] = proposePricingBandsAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(payload.bands).toEqual([
      {
        tenant_id: "tenant-1",
        transaction_type: "p2p",
        account_type: "financial_wallet",
        currency: "ZAR",
        user_type: null,
        amount_from: null,
        amount_to: null,
        fixed_fee: "5",
        variable_fee_pct: "0",
        fee_cap: null,
        fee_inclusive: false,
      },
    ]);
    // A successful proposal closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a fee proposal is blocked when a band's amounts are inverted", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("From"), "500");
    await user.type(screen.getByLabelText("To"), "100");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/upper bound must be greater than the lower bound/i),
    ).toBeInTheDocument();
    expect(proposePricingBandsAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected fee proposal shows the error to the admin", async () => {
    proposePricingBandsAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "pricing_conflict",
      message: "A schedule already exists for this scope.",
    });
    const user = await openDialog();

    const fixed = screen.getByLabelText("Fixed");
    await user.clear(fixed);
    await user.type(fixed, "5");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/pricing_conflict: A schedule already exists/),
    ).toBeInTheDocument();
    // The dialog stays open so the admin can adjust and retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Verify a wallet-only tenant is never offered the Points account type", async () => {
    // B6.1: the backend would 422 a points-scoped proposal for this tenant
    // (points_not_available), so the option must not be offered at all.
    const user = userEvent.setup();
    render(
      <CreatePricingDialog
        pointsAvailable={false}
        tenantId="tenant-1"
        services={services}
        instruments={instruments}
        trigger={<button type="button">New schedule</button>}
      />,
    );
    await user.click(screen.getByRole("button", { name: "New schedule" }));
    await screen.findByRole("dialog");

    const accountType = screen.getByLabelText("Account type");
    await user.click(accountType);

    expect(screen.getByRole("option", { name: "Wallet" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Points" })).not.toBeInTheDocument();
  });
});
