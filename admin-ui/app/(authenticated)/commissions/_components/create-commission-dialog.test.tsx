/**
 * Interaction tests for CreateCommissionDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, keep the
 * defaulted scope (service / currency), type a band's commission and submit —
 * and assert the outcome the admin cares about: a commission schedule is
 * PROPOSED through the maker-checker pipeline with exactly the band they
 * entered (and, deliberately, WITHOUT an account_type key), an invalid band is
 * refused before anything is sent, and a backend rejection is surfaced
 * verbatim. The route's server actions are mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateCommissionDialog } from "@/app/(authenticated)/commissions/_components/create-commission-dialog";
import type { Instrument, Service } from "@/lib/api-types";

const proposeCommissionBandsAction = vi.fn().mockResolvedValue({ ok: true });
const proposeCommissionUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/commissions/_actions", () => ({
  proposeCommissionBandsAction: (...args: unknown[]) =>
    proposeCommissionBandsAction(...args),
  proposeCommissionUpdateAction: (...args: unknown[]) =>
    proposeCommissionUpdateAction(...args),
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
    <CreateCommissionDialog
      tenantId="tenant-1"
      services={services}
      instruments={instruments}
      trigger={<button type="button">New commission</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New commission" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Propose a commission schedule", () => {
  it("Verify an admin can propose a new agent commission for a service", async () => {
    const user = await openDialog();

    const fixed = screen.getByLabelText("Fixed");
    await user.clear(fixed);
    await user.type(fixed, "3");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeCommissionBandsAction).toHaveBeenCalledTimes(1),
    );
    const [tenantId, payload] = proposeCommissionBandsAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(payload.bands).toEqual([
      {
        tenant_id: "tenant-1",
        transaction_type: "p2p",
        currency: "ZAR",
        user_type: null,
        amount_from: null,
        amount_to: null,
        fixed_commission: "3",
        variable_commission_pct: "0",
        commission_cap: null,
      },
    ]);
    // Commission is keyed WITHOUT account_type — the payload must not carry it.
    expect(payload.bands[0]).not.toHaveProperty("account_type");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a commission proposal is blocked when a band's amounts are inverted", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("From"), "800");
    await user.type(screen.getByLabelText("To"), "200");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/upper bound must be greater than the lower bound/i),
    ).toBeInTheDocument();
    expect(proposeCommissionBandsAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected commission proposal shows the error to the admin", async () => {
    proposeCommissionBandsAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "commission_conflict",
      message: "A commission schedule already exists for this scope.",
    });
    const user = await openDialog();

    const fixed = screen.getByLabelText("Fixed");
    await user.clear(fixed);
    await user.type(fixed, "3");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/commission_conflict: A commission schedule already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
