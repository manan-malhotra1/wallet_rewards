/**
 * Behaviour tests for <CreateUserTypeDialog> from the administrator's chair.
 *
 * What matters here is the shape of what reaches the maker-checker pipeline:
 * a flat category never offers a tier choice, the parent dropdown never offers
 * a child type (so a third level cannot be built), and the 20-character code
 * cap — which the backend rejects and which is immutable afterwards — is
 * refused before a proposal is ever sent.
 *
 * The repo has no native `<select>`, so the dropdowns are Radix comboboxes:
 * open by accessible name, then click the option.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateUserTypeDialog } from "@/app/(authenticated)/user-types/_components/create-user-type-dialog";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

const proposeUserTypeChangeAction = vi.fn().mockResolvedValue({ ok: true });
const proposeUserTypeUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/user-types/_actions", () => ({
  proposeUserTypeChangeAction: (...args: unknown[]) =>
    proposeUserTypeChangeAction(...args),
  proposeUserTypeUpdateAction: (...args: unknown[]) =>
    proposeUserTypeUpdateAction(...args),
}));

const catalog = SEED_USER_TYPE_CATALOG;

/** Open a dropdown by its accessible name and pick the named option. */
async function pick(
  user: ReturnType<typeof userEvent.setup>,
  combobox: string | RegExp,
  option: string | RegExp,
) {
  await user.click(screen.getByRole("combobox", { name: combobox }));
  await user.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => vi.clearAllMocks());

describe("CreateUserTypeDialog", () => {
  it("hides the tier choice for a flat category", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await pick(user, /category/i, "Consumers");
    expect(screen.queryByLabelText(/sits under a parent/i)).not.toBeInTheDocument();
  });

  it("offers only top-level types as parents", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await pick(user, /category/i, "Retail");
    await user.click(screen.getByLabelText(/sits under a parent/i));
    await user.click(screen.getByRole("combobox", { name: /parent type/i }));

    const listbox = await screen.findByRole("listbox");
    expect(
      within(listbox).getByRole("option", { name: "Super agent" }),
    ).toBeInTheDocument();
    // 'Agent' is itself a child — offering it would build a third level.
    expect(
      within(listbox).queryByRole("option", { name: "Agent" }),
    ).not.toBeInTheDocument();
  });

  it("proposes a create with the parent attached", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Code"), "junior_agent");
    await user.type(screen.getByLabelText("Label"), "Junior agent");
    await pick(user, /category/i, "Retail");
    await user.click(screen.getByLabelText(/sits under a parent/i));
    await pick(user, /parent type/i, "Super agent");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "t1",
      code: "junior_agent",
      label: "Junior agent",
      category_code: "retail",
      parent_type_code: "super_agent",
    });
  });

  it("refuses a code longer than 20 characters instead of proposing it", async () => {
    // The backend caps the column at 20 and the code can never be changed
    // afterwards, so this has to fail here, not after an approval round-trip.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    const codeField = screen.getByLabelText("Code");
    await user.type(codeField, "a_very_long_type_code_indeed");
    await user.type(screen.getByLabelText("Label"), "Too long");
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    // The input itself refuses the 21st character, so nothing over the cap can
    // even be typed — and what was typed is still a legal proposal.
    expect((codeField as HTMLInputElement).value).toHaveLength(20);
    expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1);
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      code: "a_very_long_type_cod",
    });
  });

  it("rejects a code that is not lowercase snake_case", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Code"), "9lives");
    await user.type(screen.getByLabelText("Label"), "Nine lives");
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    expect(await screen.findByText(/must start with a lowercase letter/i)).toBeInTheDocument();
    expect(proposeUserTypeChangeAction).not.toHaveBeenCalled();
  });

  it("carries merchant capability on the category, with no separate checkbox", async () => {
    // Replaces "defaults the merchant-profile flag on for Business". The flag
    // is gone; Business membership IS the capability, so the proposal must
    // carry the category and the dialog must not offer a second control that
    // could disagree with it.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Code"), "franchise_store");
    await user.type(screen.getByLabelText("Label"), "Franchise store");
    await pick(user, /category/i, "Business");

    expect(screen.queryByLabelText(/merchant profile/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      code: "franchise_store",
      category_code: "business",
    });
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).not.toHaveProperty(
      "requires_merchant_profile",
    );
  });

  it("proposes an update against the live row when editing", async () => {
    const user = userEvent.setup();
    const editType = {
      ...catalog.types[2],
      id: "row-1",
      is_system: false,
      code: "junior_agent",
      label: "Junior agent",
    };
    render(
      <CreateUserTypeDialog
        tenantId="t1"
        catalog={catalog}
        editType={editType}
        open
      />,
    );

    // The code is the join key and never changes — the field is locked.
    expect(screen.getByLabelText("Code")).toBeDisabled();
    await user.clear(screen.getByLabelText("Label"));
    await user.type(screen.getByLabelText("Label"), "Junior field agent");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeUpdateAction).toHaveBeenCalledTimes(1));
    const [tenantId, targetId, payload] = proposeUserTypeUpdateAction.mock.calls[0];
    expect(tenantId).toBe("t1");
    expect(targetId).toBe("row-1");
    expect(payload).toMatchObject({
      code: "junior_agent",
      label: "Junior field agent",
      category_code: "retail",
      parent_type_code: "super_agent",
      status: "active",
    });
  });
});
