/**
 * Interaction tests for <CreateUserDialog> — the admin "Register user" form.
 *
 * Registering a customer is maker-checker (Epic 3): the dialog PROPOSES a
 * create_user operation rather than creating the user directly. These tests
 * drive the form as an admin (open, fill an identifier, submit) and lock in the
 * proposal payload handed to the pipeline, the "awaiting approval" outcome, and
 * that a blank identifier / a rejected proposal are surfaced without navigating.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateUserDialog } from "@/app/(authenticated)/users/_components/create-user-dialog";

// Maker-checker propose action — unit-tested for the payload, not the pipeline.
const proposeCreateUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  proposeCreateUserAction: (...args: unknown[]) => proposeCreateUserAction(...args),
}));

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  proposeCreateUserAction.mockResolvedValue({ ok: true, operationId: "op-1" });
});

/** Open the dialog and return its content node. */
async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  render(
    <CreateUserDialog
      tenantId="tenant-1"
      trigger={<button type="button">Register user</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Register user" }));
  return screen.getByRole("dialog");
}

describe("Managing customers — registering a customer", () => {
  it("Verify creating a customer is proposed for approval", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Phone number"), "+27825550142");
    await user.click(within(dialog).getByRole("button", { name: "Submit for approval" }));

    await waitFor(() => expect(proposeCreateUserAction).toHaveBeenCalledTimes(1));
    // Proposal carries the tenant, the single identifier, and the default type.
    expect(proposeCreateUserAction.mock.calls[0][0]).toMatchObject({
      tenantId: "tenant-1",
      identifiers: [{ identifier_type: "phone", identifier_value: "+27825550142" }],
      user_type: "consumer",
    });
    // The maker is told it's awaiting approval and sent to the approvals queue.
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Create-user request submitted" }),
    );
    expect(push).toHaveBeenCalledWith("/user-operations");
  });

  it("Verify registering a customer with no identifier is blocked", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    // Submit with the identifier field left empty.
    await user.click(within(dialog).getByRole("button", { name: "Submit for approval" }));

    expect(
      await screen.findByText("Enter a phone number or email address."),
    ).toBeInTheDocument();
    expect(proposeCreateUserAction).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("Verify a rejected registration shows the reason and does not leave the form", async () => {
    proposeCreateUserAction.mockResolvedValue({
      ok: false,
      errorCode: "identifier_already_in_use",
      message: "That phone number is already registered.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Phone number"), "+27825550142");
    await user.click(within(dialog).getByRole("button", { name: "Submit for approval" }));

    expect(
      await screen.findByText(/That phone number is already registered\./),
    ).toBeInTheDocument();
    // Not navigated away — the admin can correct and retry.
    expect(push).not.toHaveBeenCalled();
  });
});
