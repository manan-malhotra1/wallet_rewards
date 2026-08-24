/**
 * Behaviour tests for <CreateUserTypeDialog> from the administrator's chair.
 *
 * What matters here is the shape of what reaches the maker-checker pipeline:
 * a flat category never offers a tier choice, the parent dropdown never offers
 * a child type (so a third level cannot be built), and the `code` — which the
 * operator no longer types — is derived from the Label on the create path and
 * carried through UNCHANGED on the edit path, because it is the immutable join
 * key every config row is scoped to.
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

  it("asks for no code at all — it is derived from the label", async () => {
    // Replaces "rejects a code that is not lowercase snake_case". The operator
    // no longer types an identifier, so there is nothing left to reject: the
    // derived code is legal by construction.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    expect(screen.queryByLabelText("Code")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Label"), "Junior Agent");
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      code: "junior_agent",
      label: "Junior Agent",
    });
  });

  it("derives a code inside the 20-character cap from an overlong label", async () => {
    // Replaces "refuses a code longer than 20 characters instead of proposing
    // it". The cap is now honoured by derivation, so a long label proposes a
    // short code instead of erroring.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(
      screen.getByLabelText("Label"),
      "Regional Distribution Partner",
    );
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    const { code } = proposeUserTypeChangeAction.mock.calls[0][0] as { code: string };
    expect(code).toBe("regional");
    expect(code.length).toBeLessThanOrEqual(20);
  });

  it("derives a legal code from a label the backend pattern would refuse", async () => {
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Label"), "9 Lives");
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      code: "type_9_lives",
    });
  });

  it("side-steps a code already taken in the catalog", async () => {
    // 'agent' is a seeded system type; the derived code must not collide with
    // it, because the backend rejects a duplicate outright.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

    await user.type(screen.getByLabelText("Label"), "Agent");
    await pick(user, /category/i, "Consumers");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeChangeAction).toHaveBeenCalledTimes(1));
    expect(proposeUserTypeChangeAction.mock.calls[0][0]).toMatchObject({
      code: "agent_2",
    });
  });

  it("carries merchant capability on the category, with no separate checkbox", async () => {
    // Replaces "defaults the merchant-profile flag on for Business". The flag
    // is gone; Business membership IS the capability, so the proposal must
    // carry the category and the dialog must not offer a second control that
    // could disagree with it.
    const user = userEvent.setup();
    render(<CreateUserTypeDialog tenantId="t1" catalog={catalog} open />);

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

    // The code is the join key and never changes — there is no field for it.
    expect(screen.queryByLabelText("Code")).not.toBeInTheDocument();
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

  it("never re-derives the code when a live type is relabelled", async () => {
    // The highest-risk regression in deriving codes: if a relabel recomputed
    // the code, every config row scoped to the old code would be orphaned and
    // every user carrying it would fall out of its own type. The new label
    // would slug to 'bureau_de_change' — the payload must still say 'agent_x'.
    const user = userEvent.setup();
    const editType = {
      ...catalog.types[1],
      id: "row-9",
      is_system: false,
      code: "agent_x",
      label: "Agent X",
    };
    render(
      <CreateUserTypeDialog tenantId="t1" catalog={catalog} editType={editType} open />,
    );

    await user.clear(screen.getByLabelText("Label"));
    await user.type(screen.getByLabelText("Label"), "Bureau de change");
    await user.click(screen.getByRole("button", { name: "Propose change" }));

    await waitFor(() => expect(proposeUserTypeUpdateAction).toHaveBeenCalledTimes(1));
    const payload = proposeUserTypeUpdateAction.mock.calls[0][2];
    expect(payload).toMatchObject({ code: "agent_x", label: "Bureau de change" });
    expect(proposeUserTypeChangeAction).not.toHaveBeenCalled();
  });
});
