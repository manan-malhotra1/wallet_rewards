/**
 * Interaction tests for CreateLimitDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, keep the
 * defaulted scope (service / account / currency), type a per-transaction cap
 * and submit — and assert the outcome the admin cares about: a service-limit
 * is PROPOSED through the maker-checker pipeline with exactly the cap they
 * entered, a proposal with no caps at all is refused before anything is sent,
 * and a backend rejection is surfaced verbatim. The route's server actions are
 * mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateLimitDialog } from "@/app/(authenticated)/limits/_components/create-limit-dialog";
import type { Instrument, Service } from "@/lib/api-types";

const proposeLimitCreateAction = vi.fn().mockResolvedValue({ ok: true });
const proposeLimitUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/limits/_actions", () => ({
  proposeLimitCreateAction: (...args: unknown[]) => proposeLimitCreateAction(...args),
  proposeLimitUpdateAction: (...args: unknown[]) => proposeLimitUpdateAction(...args),
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
    <CreateLimitDialog
      tenantId="tenant-1"
      services={services}
      instruments={instruments}
      trigger={<button type="button">New limit</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New limit" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Propose a service limit", () => {
  it("Verify an admin can propose a per-transaction cap for a service", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Max amount"), "5000");
    await user.type(screen.getByLabelText("Daily count cap"), "10");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeLimitCreateAction).toHaveBeenCalledTimes(1));
    const [tenantId, payload] = proposeLimitCreateAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(payload).toMatchObject({
      tenant_id: "tenant-1",
      transaction_type: "p2p",
      account_type: "financial_wallet",
      currency: "ZAR",
      user_type: null,
      max_amount: "5000",
      daily_count_cap: 10,
    });
    // A cap left blank is omitted, not sent as an empty string.
    expect(payload.min_amount).toBeUndefined();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a limit proposal is blocked when no cap is set", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(await screen.findByText("Set at least one cap.")).toBeInTheDocument();
    expect(proposeLimitCreateAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected limit proposal shows the error to the admin", async () => {
    proposeLimitCreateAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "limit_conflict",
      message: "A limit already exists for this scope.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Max amount"), "5000");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/limit_conflict: A limit already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
