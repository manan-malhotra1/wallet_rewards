/**
 * Interaction tests for CreateTaxDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, keep the
 * defaulted currency, type the fee/commission tax rates, toggle an inclusive
 * flag and submit — and assert the outcome the admin cares about: a tax config
 * is PROPOSED through the maker-checker pipeline with exactly the rates and
 * flags they entered, an invalid rate the backend refuses is surfaced, and a
 * generic backend failure is shown while the dialog stays open. The route's
 * server actions are mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateTaxDialog } from "@/app/(authenticated)/taxes/_components/create-tax-dialog";
import type { Instrument } from "@/lib/api-types";

const proposeTaxChangeAction = vi.fn().mockResolvedValue({ ok: true });
const proposeTaxUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/taxes/_actions", () => ({
  proposeTaxChangeAction: (...args: unknown[]) => proposeTaxChangeAction(...args),
  proposeTaxUpdateAction: (...args: unknown[]) => proposeTaxUpdateAction(...args),
}));

const reviseAndResubmitConfigRequestAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  reviseAndResubmitConfigRequestAction: (...args: unknown[]) =>
    reviseAndResubmitConfigRequestAction(...args),
}));

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
    <CreateTaxDialog
      tenantId="tenant-1"
      instruments={instruments}
      trigger={<button type="button">New tax</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New tax" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Propose a tax config", () => {
  it("Verify an admin can propose tax rates for a currency", async () => {
    const user = await openDialog();

    // Both rate fields default to "0", so clear before typing the real rate.
    const feePct = screen.getByLabelText("Fee tax %");
    const commPct = screen.getByLabelText("Commission tax %");
    await user.clear(feePct);
    await user.type(feePct, "0.15");
    await user.clear(commPct);
    await user.type(commPct, "0.15");
    await user.click(screen.getByRole("checkbox", { name: /Fee tax inclusive/ }));
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeTaxChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeTaxChangeAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      currency: "ZAR",
      fee_tax_pct: "0.15",
      commission_tax_pct: "0.15",
      fee_tax_inclusive: true,
      commission_tax_inclusive: false,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a tax proposal with an invalid rate is rejected with a reason", async () => {
    proposeTaxChangeAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "validation_error",
      message: "Tax rate must be between 0 and 1.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Fee tax %"), "1.5");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/validation_error: Tax rate must be between 0 and 1/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Verify a rejected tax proposal shows the error to the admin", async () => {
    proposeTaxChangeAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "internal_error",
      message: "Upstream config service is unavailable.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Fee tax %"), "0.15");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/internal_error: Upstream config service is unavailable/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
