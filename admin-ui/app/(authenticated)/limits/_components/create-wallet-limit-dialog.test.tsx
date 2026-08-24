/**
 * Interaction tests for CreateWalletLimitDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, keep the
 * defaulted currency, type a max wallet balance and a send cap and submit —
 * and assert the outcome the admin cares about: a wallet-limit is PROPOSED
 * through the maker-checker pipeline with the max balance and count caps
 * coerced to numbers, a proposal with neither a max balance nor any cap is
 * refused before anything is sent, and a backend rejection is surfaced
 * verbatim. The route's server actions are mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateWalletLimitDialog } from "@/app/(authenticated)/limits/_components/create-wallet-limit-dialog";
import type { Instrument } from "@/lib/api-types";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

const proposeWalletLimitCreateAction = vi.fn().mockResolvedValue({ ok: true });
const proposeWalletLimitUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/limits/_actions", () => ({
  proposeWalletLimitCreateAction: (...args: unknown[]) =>
    proposeWalletLimitCreateAction(...args),
  proposeWalletLimitUpdateAction: (...args: unknown[]) =>
    proposeWalletLimitUpdateAction(...args),
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
    <CreateWalletLimitDialog
      tenantId="tenant-1"
      instruments={instruments}
      catalog={SEED_USER_TYPE_CATALOG}
      trigger={<button type="button">New wallet limit</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New wallet limit" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Propose a wallet limit", () => {
  it("Verify an admin can propose a max wallet balance and a send cap", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Max balance"), "50000");
    await user.type(screen.getByLabelText("Send · daily count"), "10");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeWalletLimitCreateAction).toHaveBeenCalledTimes(1),
    );
    const [tenantId, payload] = proposeWalletLimitCreateAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(payload).toMatchObject({
      tenant_id: "tenant-1",
      currency: "ZAR",
      user_type: null,
      max_balance: "50000",
      // Count caps are coerced to numbers, not left as strings.
      send_daily_count_cap: 10,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a wallet-limit proposal is blocked when nothing is set", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText("Set a max balance or at least one cap."),
    ).toBeInTheDocument();
    expect(proposeWalletLimitCreateAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected wallet-limit proposal shows the error to the admin", async () => {
    proposeWalletLimitCreateAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "wallet_limit_conflict",
      message: "A wallet limit already exists for this currency.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Max balance"), "50000");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText(/wallet_limit_conflict: A wallet limit already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
