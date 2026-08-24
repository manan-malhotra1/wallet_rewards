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
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

// Maker-checker propose action — unit-tested for the payload, not the pipeline.
const proposeCreateUserAction = vi.fn();
const lookupUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  proposeCreateUserAction: (...args: unknown[]) => proposeCreateUserAction(...args),
  lookupUserAction: (...args: unknown[]) => lookupUserAction(...args),
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
  lookupUserAction.mockResolvedValue({
    ok: true,
    user: {
      id: "boss-1",
      full_name: "Thabo Nkosi",
      user_type: "super_agent",
      masked_phone: "+2782 *** 0100",
    },
  });
});

/** Open a dropdown by its accessible name and pick the named option. */
async function pick(
  user: ReturnType<typeof userEvent.setup>,
  combobox: string | RegExp,
  option: string | RegExp,
) {
  await user.click(screen.getByRole("combobox", { name: combobox }));
  await user.click(await screen.findByRole("option", { name: option }));
}

/** Open the dialog and return its content node. */
async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  render(
    <CreateUserDialog
      tenantId="tenant-1"
      catalog={SEED_USER_TYPE_CATALOG}
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

  it("Verify a supervisor is only offered for a type that has a parent", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    // Consumer is top-level: no supervisor slot exists at all.
    expect(
      within(dialog).queryByLabelText(/supervisor's phone/i),
    ).not.toBeInTheDocument();

    // Agent sits under a Super agent, so the block appears.
    await pick(user, /category/i, "Retail");
    await pick(user, /user type/i, "Agent");
    expect(within(dialog).getByLabelText(/supervisor's phone/i)).toBeInTheDocument();
  });

  it("Verify a confirmed supervisor travels as an identifier, not an id", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Phone number"), "+27825550142");
    await pick(user, /category/i, "Retail");
    await pick(user, /user type/i, "Agent");
    await user.type(
      within(dialog).getByLabelText(/supervisor's phone/i),
      "+27825550100",
    );
    await user.click(within(dialog).getByRole("button", { name: /look up/i }));
    await within(dialog).findByText("Thabo Nkosi");

    await user.click(within(dialog).getByRole("button", { name: "Submit for approval" }));

    await waitFor(() => expect(proposeCreateUserAction).toHaveBeenCalledTimes(1));
    expect(proposeCreateUserAction.mock.calls[0][0]).toMatchObject({
      user_type: "agent",
      parent_identifier: {
        identifier_type: "phone",
        identifier_value: "+27825550100",
      },
    });
  });

  it("Verify the supervisor key is omitted entirely when none is attached", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Phone number"), "+27825550143");
    await pick(user, /category/i, "Retail");
    await pick(user, /user type/i, "Agent");
    await user.click(within(dialog).getByRole("button", { name: "Submit for approval" }));

    await waitFor(() => expect(proposeCreateUserAction).toHaveBeenCalledTimes(1));
    expect(proposeCreateUserAction.mock.calls[0][0]).not.toHaveProperty(
      "parent_identifier",
    );
  });
});
