/**
 * Interaction tests for <EditUserDrawer> — the inline "Edit user" affordance.
 *
 * Editing a customer is maker-checker (Epic 3): saving PROPOSES an update_user
 * operation with ONLY the changed fields, and a user with an open request can't
 * stack another. These tests drive the drawer as an admin (open, change a
 * field, submit) and assert the minimal proposal payload, the no-op guard, the
 * server-error surface, and the already-pending block.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditUserDrawer } from "@/app/(authenticated)/users/_components/edit-user-drawer";
import type { UserIdentifier } from "@/lib/api-types";

const proposeUpdateUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  proposeUpdateUserAction: (...args: unknown[]) => proposeUpdateUserAction(...args),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

const identifiers: UserIdentifier[] = [
  { id: "id-1", identifier_type: "phone", identifier_value: "+27825550142", verified: true },
];

const current = {
  firstName: "Jane",
  lastName: "Mokoena",
  status: "active" as const,
  userType: "consumer" as const,
};

function renderDrawer(openUpdate: { id: string; status: string } | null = null) {
  return render(
    <EditUserDrawer
      userId="user-1"
      tenantId="tenant-1"
      current={current}
      identifiers={identifiers}
      openUpdate={openUpdate}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  proposeUpdateUserAction.mockResolvedValue({ ok: true, operationId: "op-1" });
});

describe("Managing customers — editing a customer", () => {
  it("Verify editing a customer is proposed for approval with only the changed field", async () => {
    const user = userEvent.setup();
    renderDrawer();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const drawer = screen.getByRole("dialog");

    const firstName = within(drawer).getByLabelText("First name");
    await user.clear(firstName);
    await user.type(firstName, "Janet");
    await user.click(within(drawer).getByRole("button", { name: "Submit for approval" }));

    await waitFor(() => expect(proposeUpdateUserAction).toHaveBeenCalledTimes(1));
    // Only the field the admin actually changed is proposed — nothing else.
    expect(proposeUpdateUserAction.mock.calls[0][0]).toEqual({
      tenantId: "tenant-1",
      target_user_id: "user-1",
      first_name: "Janet",
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Edit request submitted" }),
    );
    expect(push).toHaveBeenCalledWith("/user-operations");
  });

  it("Verify submitting an edit with no changes is blocked", async () => {
    const user = userEvent.setup();
    renderDrawer();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const drawer = screen.getByRole("dialog");

    // Submit without touching any field.
    await user.click(within(drawer).getByRole("button", { name: "Submit for approval" }));

    expect(
      await screen.findByText("Change at least one field before submitting."),
    ).toBeInTheDocument();
    expect(proposeUpdateUserAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected edit shows the reason", async () => {
    proposeUpdateUserAction.mockResolvedValue({
      ok: false,
      errorCode: "validation_error",
      message: "Status transition not allowed.",
    });
    const user = userEvent.setup();
    renderDrawer();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const drawer = screen.getByRole("dialog");

    const lastName = within(drawer).getByLabelText("Last name");
    await user.clear(lastName);
    await user.type(lastName, "Ncube");
    await user.click(within(drawer).getByRole("button", { name: "Submit for approval" }));

    expect(await screen.findByText(/Status transition not allowed\./)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("Verify a customer with a pending edit cannot have another proposed", async () => {
    const user = userEvent.setup();
    renderDrawer({ id: "op-existing", status: "PENDING" });
    await user.click(screen.getByRole("button", { name: "Edit" }));

    // The drawer surfaces the open request instead of the editable form.
    expect(
      await screen.findByText("An edit is already awaiting approval"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("First name")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Go to User approvals" }),
    ).toBeInTheDocument();
    expect(proposeUpdateUserAction).not.toHaveBeenCalled();
  });
});
