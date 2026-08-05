/**
 * Interaction tests for <CreateBudgetDialog> — the admin "New reward budget"
 * form.
 *
 * These drive the dialog as an admin does — open it, pick a currency, adjust
 * the scope/window/cap, submit — and assert the outcome: currency comes from
 * the tenant's instrument dropdown (not free text), a tenant-wide budget in a
 * multi-currency tenant fans out into one create call per filled-in currency,
 * a non-positive cap is refused before anything is sent, and a backend
 * rejection stays on screen. The server action is mocked; no backend is
 * touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateBudgetDialog } from "@/app/(authenticated)/budgets/_components/create-budget-dialog";

const createBudgetAction = vi.fn();
vi.mock("@/app/(authenticated)/budgets/_actions", () => ({
  createBudgetAction: (...args: unknown[]) => createBudgetAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  createBudgetAction.mockResolvedValue({ ok: true });
});

/** Open the dialog and return its content node. */
async function openDialog(
  user: ReturnType<typeof userEvent.setup>,
  currencies: string[] = ["PTS"],
) {
  render(
    <CreateBudgetDialog
      tenantId="tenant-1"
      currencies={currencies}
      trigger={<button type="button">New budget</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New budget" }));
  return screen.findByRole("dialog");
}

describe("Managing reward budgets — creating a budget", () => {
  it("Verify a single-currency tenant creates a tenant-wide budget with the default currency", async () => {
    const user = userEvent.setup();
    await openDialog(user);

    // Defaults: tenant scope, PTS currency (only option), lifetime, cap 10000.
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createBudgetAction).toHaveBeenCalledTimes(1));
    expect(createBudgetAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      scope_type: "tenant",
      scope_id: undefined,
      currency: "PTS",
      window_type: "lifetime",
      cap_amount: "10000",
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Budget created" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a tenant-wide budget in a multi-currency tenant creates one budget per filled-in currency", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, ["PTS", "ZAR", "USD"]);

    // Per-currency caps: fill PTS + ZAR, leave USD blank (should be skipped).
    await user.type(within(dialog).getByLabelText("Cap for PTS"), "50000");
    await user.type(within(dialog).getByLabelText("Cap for ZAR"), "1000");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createBudgetAction).toHaveBeenCalledTimes(2));
    const payloads = createBudgetAction.mock.calls.map((c) => c[0]);
    expect(payloads).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ currency: "PTS", cap_amount: "50000", scope_type: "tenant" }),
        expect.objectContaining({ currency: "ZAR", cap_amount: "1000", scope_type: "tenant" }),
      ]),
    );
    // USD was blank — no budget for it.
    expect(payloads.some((p) => p.currency === "USD")).toBe(false);
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "2 budgets created" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a multi-currency tenant-wide budget refuses submit when no cap is entered", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user, ["PTS", "ZAR"]);

    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Enter a cap for at least one currency."),
    ).toBeInTheDocument();
    expect(createBudgetAction).not.toHaveBeenCalled();
  });

  it("Verify a budget cannot be created without a positive cap", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.clear(within(dialog).getByLabelText("Cap amount"));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Cap must be a positive number."),
    ).toBeInTheDocument();
    expect(createBudgetAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected budget shows the reason and keeps the form open", async () => {
    createBudgetAction.mockResolvedValue({
      ok: false,
      errorCode: "budget_overlap",
      message: "A lifetime budget already exists for this tenant.",
    });
    const user = userEvent.setup();
    await openDialog(user);

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/A lifetime budget already exists for this tenant\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
