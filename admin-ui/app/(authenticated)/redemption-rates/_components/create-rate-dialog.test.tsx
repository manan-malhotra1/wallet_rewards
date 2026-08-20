/**
 * Behaviour tests for CreateRateDialog (Pay-PRD-1210/1295).
 *
 * The dialog is unit-tested for the payload it hands the maker-checker
 * pipeline: blank caps are OMITTED (backend expresses "uncapped" as absent),
 * filled caps travel as strings, the %-cap is validated to (0, 100], and edit
 * mode proposes an `update` against the live row with its currency locked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateRateDialog } from "@/app/(authenticated)/redemption-rates/_components/create-rate-dialog";
import type { PointsConversionRate } from "@/lib/api-types";

const proposeConversionRateChangeAction = vi.fn().mockResolvedValue({ ok: true });
const proposeConversionRateUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/redemption-rates/_actions", () => ({
  proposeConversionRateChangeAction: (...args: unknown[]) =>
    proposeConversionRateChangeAction(...args),
  proposeConversionRateUpdateAction: (...args: unknown[]) =>
    proposeConversionRateUpdateAction(...args),
}));

const reviseAndResubmitConfigRequestAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  reviseAndResubmitConfigRequestAction: (...args: unknown[]) =>
    reviseAndResubmitConfigRequestAction(...args),
}));

/** A live ZAR rate with both anti-drain caps set. */
const zarRate: PointsConversionRate = {
  id: "rate-zar",
  tenant_id: "tenant-1",
  currency: "ZAR",
  points_per_unit: "100",
  value_per_unit: "10",
  max_points_per_txn: "50",
  max_balance_pct_per_txn: "10",
  status: "active",
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Conversion rate form", () => {
  it("Verify blank caps are omitted from the proposal (uncapped)", async () => {
    const user = userEvent.setup();
    render(<CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        open
      />);

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeConversionRateChangeAction).toHaveBeenCalledTimes(1),
    );
    const payload = proposeConversionRateChangeAction.mock.calls[0][0];
    expect(payload).toMatchObject({
      tenant_id: "tenant-1",
      currency: "ZAR",
      points_per_unit: "100",
      value_per_unit: "10",
    });
    expect(payload).not.toHaveProperty("max_points_per_txn");
    expect(payload).not.toHaveProperty("max_balance_pct_per_txn");
  });

  it("Verify filled anti-drain caps travel with the proposal", async () => {
    const user = userEvent.setup();
    render(<CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        open
      />);

    await user.type(screen.getByLabelText("Max points per txn"), "50");
    await user.type(screen.getByLabelText("Max % of balance per txn"), "10");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeConversionRateChangeAction).toHaveBeenCalledTimes(1),
    );
    expect(proposeConversionRateChangeAction.mock.calls[0][0]).toMatchObject({
      max_points_per_txn: "50",
      max_balance_pct_per_txn: "10",
    });
  });

  it("Verify a % cap above 100 is refused before proposing", async () => {
    const user = userEvent.setup();
    render(<CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        open
      />);

    await user.type(screen.getByLabelText("Max % of balance per txn"), "150");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText("The % of balance cap must be between 0 and 100."),
    ).toBeInTheDocument();
    expect(proposeConversionRateChangeAction).not.toHaveBeenCalled();
  });

  it("Verify editing a live rate proposes an update with its currency locked", async () => {
    const user = userEvent.setup();
    render(<CreateRateDialog
        tenantId="tenant-1"
        currencies={["ZAR", "INR"]}
        open
        editRate={zarRate}
      />);

    expect(screen.getByRole("combobox", { name: /currency/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeConversionRateUpdateAction).toHaveBeenCalledTimes(1),
    );
    const [tenantId, targetId, payload] = proposeConversionRateUpdateAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(targetId).toBe("rate-zar");
    expect(payload).toMatchObject({
      currency: "ZAR",
      points_per_unit: "100",
      value_per_unit: "10",
      max_points_per_txn: "50",
      max_balance_pct_per_txn: "10",
    });
  });

  it("Verify a zero rate side is refused before proposing", async () => {
    const user = userEvent.setup();
    render(<CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        open
      />);

    await user.clear(screen.getByLabelText("= Value"));
    await user.type(screen.getByLabelText("= Value"), "0");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(
      await screen.findByText("Both sides of the rate must be positive numbers."),
    ).toBeInTheDocument();
    expect(proposeConversionRateChangeAction).not.toHaveBeenCalled();
  });

  it("Verify the currency dropdown offers only the tenant's currencies", async () => {
    const user = userEvent.setup();
    render(
      <CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        open
      />,
    );

    await user.click(screen.getByRole("combobox", { name: /currency/i }));
    expect(screen.getByRole("option", { name: "ZAR" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "INR" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "USD" })).not.toBeInTheDocument();
  });

  it("Verify a currency that already has a rate is not offered again", async () => {
    const user = userEvent.setup();
    render(
      <CreateRateDialog
        tenantId="tenant-1"
        defaultCurrency="ZAR"
        currencies={["ZAR", "INR"]}
        configuredCurrencies={["ZAR"]}
        open
      />,
    );

    await user.click(screen.getByRole("combobox", { name: /currency/i }));
    // ZAR is taken (one rate per currency) — only INR remains selectable.
    expect(screen.queryByRole("option", { name: "ZAR" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "INR" })).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: "INR" }));
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() =>
      expect(proposeConversionRateChangeAction).toHaveBeenCalledTimes(1),
    );
    expect(proposeConversionRateChangeAction.mock.calls[0][0]).toMatchObject({
      currency: "INR",
    });
  });
});
