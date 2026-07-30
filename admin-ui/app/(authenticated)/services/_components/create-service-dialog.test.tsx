/**
 * Interaction tests for CreateServiceDialog from the administrator's chair.
 *
 * These drive the real dialog the way an admin does — open it, type the
 * immutable code and a display name and submit — and assert the outcome the
 * admin cares about: a new service is created with exactly the code and name
 * they entered, a malformed code is refused before anything is sent, and a
 * backend rejection is surfaced verbatim while the dialog stays open. The
 * route's server action is mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateServiceDialog } from "@/app/(authenticated)/services/_components/create-service-dialog";

const createServiceAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/services/_actions", () => ({
  createServiceAction: (...args: unknown[]) => createServiceAction(...args),
}));

/** Render the dialog behind a trigger, open it, and return the userEvent instance. */
async function openDialog() {
  const user = userEvent.setup();
  render(
    <CreateServiceDialog
      tenantId="tenant-1"
      trigger={<button type="button">New service</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New service" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create a service", () => {
  it("Verify an admin can add a new service to the catalog", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "bill_pay");
    await user.type(screen.getByLabelText("Display name"), "Bill Pay");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createServiceAction).toHaveBeenCalledTimes(1));
    expect(createServiceAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      code: "bill_pay",
      display_name: "Bill Pay",
      description: undefined,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a service with a malformed code is blocked", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Code"), "Bill Pay");
    await user.type(screen.getByLabelText("Display name"), "Bill Pay");
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

    await user.type(screen.getByLabelText("Code"), "bill_pay");
    await user.type(screen.getByLabelText("Display name"), "Bill Pay");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/duplicate_code: A service with this code already exists/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
