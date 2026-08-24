/**
 * Interaction tests for CreateServiceDialog from the administrator's chair.
 *
 * The dialog only creates DERIVED services, so every test picks a base first.
 * Beyond the happy path these pin the two ways an admin could otherwise build
 * a service that can never work: omitting the base (rejected by the backend
 * with a 422 the admin would have to decode), and leaving the policy open on a
 * base that is itself restricted (the backend's narrowing rule treats an empty
 * derived policy as "wider than the base" and refuses it). Both are caught in
 * the form. The route's server action is mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateServiceDialog } from "@/app/(authenticated)/services/_components/create-service-dialog";
import type { Service } from "@/lib/api-types";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

const createServiceAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/services/_actions", () => ({
  createServiceAction: (...args: unknown[]) => createServiceAction(...args),
}));

/** Build a catalog row; defaults describe an unrestricted derivable base. */
function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P Transfer",
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
    ...overrides,
  };
}

/** Render the dialog behind a trigger, open it, and return the userEvent instance. */
async function openDialog(services: Service[] = [makeService()]) {
  const user = userEvent.setup();
  render(
    <CreateServiceDialog
      tenantId="tenant-1"
      services={services}
      catalog={SEED_USER_TYPE_CATALOG}
      trigger={<button type="button">New service</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New service" }));
  await screen.findByRole("dialog");
  return user;
}

/** Choose a base service by display name from the "Based on" dropdown. */
async function pickBase(
  user: ReturnType<typeof userEvent.setup>,
  name = "P2P Transfer",
) {
  await user.click(screen.getByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: new RegExp(name) }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create a derived service", () => {
  it("Verify an admin can add a variant of a base service", async () => {
    const user = await openDialog();

    await pickBase(user);
    await user.type(screen.getByLabelText("Code"), "p2p_diaspora");
    await user.type(screen.getByLabelText("Display name"), "Diaspora Transfer");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createServiceAction).toHaveBeenCalledTimes(1));
    expect(createServiceAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      code: "p2p_diaspora",
      display_name: "Diaspora Transfer",
      description: undefined,
      base_service_code: "p2p",
      // Base is unrestricted, so no chips selected → unrestricted (null).
      allowed_user_types: null,
      allowed_channels: null,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a service cannot be created without choosing a base", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "p2p_diaspora");
    await user.type(screen.getByLabelText("Display name"), "Diaspora Transfer");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/Choose the base service this one runs on/),
    ).toBeInTheDocument();
    expect(createServiceAction).not.toHaveBeenCalled();
  });

  it("Verify only derivable, active bases are offered", async () => {
    const user = await openDialog([
      makeService(),
      // A base the platform forbids deriving from (server-marked).
      makeService({
        id: "svc-2",
        code: "change_pin",
        display_name: "Change PIN",
        derivable: false,
      }),
      // Deriving from a derivation is not a thing.
      makeService({
        id: "svc-3",
        code: "p2p_diaspora",
        display_name: "Diaspora Transfer",
        kind: "derived",
        base_service_code: "p2p",
        derivable: false,
      }),
      // A switched-off base would produce a service that cannot run.
      makeService({
        id: "svc-4",
        code: "cashout",
        display_name: "Cash Out",
        status: "disabled",
      }),
    ]);

    await user.click(screen.getByRole("combobox"));

    expect(await screen.findByRole("option", { name: /P2P Transfer/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Change PIN/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Diaspora Transfer/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Cash Out/ })).not.toBeInTheDocument();
  });

  it("Verify a restricted base offers only its own user types, pre-selected", async () => {
    const user = await openDialog([
      makeService({
        display_name: "Merchant Cash In",
        code: "merchant_cashin",
        allowed_user_types: ["merchant", "head_merchant"],
      }),
    ]);

    await pickBase(user, "Merchant Cash In");

    // Seeded from the base: the widest legal starting point, so the common
    // "same audience, different price" case needs no chip clicks.
    expect(screen.getByRole("button", { name: "Merchant" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Head merchant" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // A user type the base excludes is not even offered — it would be refused.
    expect(screen.queryByRole("button", { name: "Consumer" })).not.toBeInTheDocument();
  });

  it("Verify clearing the policy on a restricted base is blocked in the form", async () => {
    const user = await openDialog([
      makeService({
        display_name: "Merchant Cash In",
        code: "merchant_cashin",
        allowed_user_types: ["merchant"],
      }),
    ]);

    await pickBase(user, "Merchant Cash In");
    await user.type(screen.getByLabelText("Code"), "merchant_cashin_promo");
    await user.type(screen.getByLabelText("Display name"), "Merchant Cash In (Promo)");
    // Deselect the only permitted user type: an empty derived policy reads as
    // "unrestricted", which is WIDER than the base, so the backend refuses it.
    await user.click(screen.getByRole("button", { name: "Merchant", pressed: true }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/Pick at least one user type/)).toBeInTheDocument();
    expect(createServiceAction).not.toHaveBeenCalled();
  });

  it("Verify the admin can narrow a variant to chosen user types and channels", async () => {
    const user = await openDialog();

    await pickBase(user);
    await user.type(screen.getByLabelText("Code"), "p2p_diaspora");
    await user.type(screen.getByLabelText("Display name"), "Diaspora Transfer");
    await user.click(screen.getByRole("button", { name: "Consumer", pressed: false }));
    await user.click(screen.getByRole("button", { name: "Agent", pressed: false }));
    await user.click(screen.getByRole("button", { name: "USSD", pressed: false }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createServiceAction).toHaveBeenCalledTimes(1));
    expect(createServiceAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      code: "p2p_diaspora",
      display_name: "Diaspora Transfer",
      description: undefined,
      base_service_code: "p2p",
      allowed_user_types: ["consumer", "agent"],
      allowed_channels: ["ussd"],
    });
  });

  it("Verify a service with a malformed code is blocked", async () => {
    const user = await openDialog();

    await pickBase(user);
    await user.type(screen.getByLabelText("Code"), "Diaspora Transfer");
    await user.type(screen.getByLabelText("Display name"), "Diaspora Transfer");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/Code must be lowercase letters, numbers, and underscores/),
    ).toBeInTheDocument();
    expect(createServiceAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected service creation shows the error to the admin", async () => {
    createServiceAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "duplicate_code",
      message: "A service with this code already exists.",
    });
    const user = await openDialog();

    await pickBase(user);
    await user.type(screen.getByLabelText("Code"), "p2p_diaspora");
    await user.type(screen.getByLabelText("Display name"), "Diaspora Transfer");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/duplicate_code: A service with this code already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
