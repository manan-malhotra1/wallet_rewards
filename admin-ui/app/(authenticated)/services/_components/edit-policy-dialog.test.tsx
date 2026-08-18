/**
 * Interaction tests for EditServicePolicyDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it on an existing
 * service, flip the restrict toggles and pick chips — and assert the outcome
 * the admin cares about: only the dimensions they actually changed are sent,
 * the unrestricted (`null`) vs restrict-to-none (`[]`) distinction is
 * preserved on the wire, and an untouched dimension is left out of the PATCH.
 * The route's server action is mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditServicePolicyDialog } from "@/app/(authenticated)/services/_components/edit-policy-dialog";
import type { Service } from "@/lib/api-types";

const updateServiceAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/services/_actions", () => ({
  updateServiceAction: (...args: unknown[]) => updateServiceAction(...args),
}));

/** Minimal Service row with overridable policy fields. */
function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "bill_pay",
    display_name: "Bill Pay",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Render the dialog behind a trigger, open it, and return the userEvent instance. */
async function openDialog(service: Service) {
  const user = userEvent.setup();
  render(
    <EditServicePolicyDialog
      service={service}
      tenantId="tenant-1"
      trigger={<button type="button">Edit policy</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Edit policy" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Edit a service access policy", () => {
  it("Verify restricting only the user types sends just that field as an allow-list", async () => {
    const user = await openDialog(makeService());

    await user.click(screen.getByLabelText("Restrict who can initiate"));
    await user.click(screen.getByRole("button", { name: "Consumer", pressed: false }));
    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(updateServiceAction).toHaveBeenCalledTimes(1));
    expect(updateServiceAction.mock.calls[0]).toEqual([
      "svc-1",
      "tenant-1",
      { allowed_user_types: ["consumer"] },
    ]);
  });

  it("Verify restrict-to-none sends [] (operator-only), not null", async () => {
    const user = await openDialog(makeService());

    // Turn on the restriction but pick no channels → restrict to none.
    await user.click(screen.getByLabelText("Restrict channels"));
    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(updateServiceAction).toHaveBeenCalledTimes(1));
    expect(updateServiceAction.mock.calls[0]).toEqual([
      "svc-1",
      "tenant-1",
      { allowed_channels: [] },
    ]);
  });

  it("Verify lifting a restriction sends null (unrestricted)", async () => {
    const user = await openDialog(
      makeService({ allowed_user_types: ["consumer"] }),
    );

    await user.click(screen.getByLabelText("Restrict who can initiate"));
    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() => expect(updateServiceAction).toHaveBeenCalledTimes(1));
    expect(updateServiceAction.mock.calls[0]).toEqual([
      "svc-1",
      "tenant-1",
      { allowed_user_types: null },
    ]);
  });

  it("Verify saving with no changes sends nothing and closes", async () => {
    const user = await openDialog(
      makeService({ allowed_user_types: ["consumer"], allowed_channels: ["web"] }),
    );

    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(updateServiceAction).not.toHaveBeenCalled();
  });
});
