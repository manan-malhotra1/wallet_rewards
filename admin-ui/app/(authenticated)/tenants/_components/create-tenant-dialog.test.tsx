/**
 * Behaviour tests for CreateTenantDialog.
 *
 * Covers the admin-facing guarantees: the form renders its fields, a valid
 * submit hands the entered name / business type / currency (+ brand colours)
 * to the create action, an empty name blocks the submit, and a duplicate-name
 * server rejection surfaces in the dialog. The server action is mocked — the
 * dialog is unit-tested for what it submits, not the backend.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateTenantDialog } from "@/app/(authenticated)/tenants/_components/create-tenant-dialog";
import { DEFAULT_ACCENT, DEFAULT_LIGHT } from "@/lib/brand-palette";

const createTenantAction = vi
  .fn()
  .mockResolvedValue({ ok: true, id: "tenant-new" });
vi.mock("@/app/(authenticated)/tenants/_actions", () => ({
  createTenantAction: (...args: unknown[]) => createTenantAction(...args),
}));

/** Open the dialog and return the userEvent instance. */
async function openDialog() {
  const user = userEvent.setup();
  render(
    <CreateTenantDialog trigger={<button>New tenant</button>} />,
  );
  await user.click(screen.getByRole("button", { name: "New tenant" }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create tenant dialog", () => {
  it("Verify the create-tenant form renders its name, business type and currency fields", async () => {
    await openDialog();

    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Business type")).toBeInTheDocument();
    expect(screen.getByLabelText("Base currency")).toBeInTheDocument();
  });

  it("Verify a valid submit creates the tenant with the entered name, currency and brand colours", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Acme Fintech");
    await user.type(screen.getByLabelText("Base currency"), "zar");

    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    await waitFor(() => expect(createTenantAction).toHaveBeenCalledTimes(1));
    const [payload] = createTenantAction.mock.calls[0];
    expect(payload).toEqual({
      name: "Acme Fintech",
      business_type: "wallet",
      base_currency: "ZAR",
      brand_accent_color: DEFAULT_ACCENT,
      brand_light_color: DEFAULT_LIGHT,
      brand_icon_url: null,
    });
  });

  it("Verify an empty name blocks creating the tenant", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Base currency"), "ZAR");

    const create = screen.getByRole("button", { name: "Create tenant" });
    expect(create).toBeDisabled();
    expect(createTenantAction).not.toHaveBeenCalled();
  });

  it("Verify a duplicate-name rejection surfaces in the dialog", async () => {
    createTenantAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "tenant_name_conflict",
      message: "A tenant with that name already exists.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Acme Fintech");
    await user.type(screen.getByLabelText("Base currency"), "ZAR");

    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          /tenant_name_conflict: A tenant with that name already exists\./,
        ),
      ).toBeInTheDocument(),
    );
  });
});
