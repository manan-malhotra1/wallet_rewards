/**
 * Interaction tests for <UserTypeSelect> from the administrator's chair.
 *
 * The control is the one place every config dialog now narrows a rule to a
 * kind of customer, so what matters is that the second list stays shut until a
 * category is chosen, that it only ever offers that category's types, and that
 * an existing config reopens already narrowed to the stored type.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import { UserTypeSelect } from "@/components/user-type-select";
import type { UserTypeCatalog } from "@/lib/api-types";

const catalog: UserTypeCatalog = {
  categories: [
    { code: "consumer", label: "Consumers", display_order: 1, supports_hierarchy: false },
    { code: "retail", label: "Retail", display_order: 2, supports_hierarchy: true },
  ],
  types: [
    { code: "consumer", label: "Consumer", category_code: "consumer", parent_type_code: null,
      is_system: true, status: "active" },
    { code: "agent", label: "Agent", category_code: "retail", parent_type_code: "super_agent",
      is_system: true, status: "active" },
  ],
};

/** Open a dropdown by its accessible name and pick the named option. */
async function pick(
  user: ReturnType<typeof userEvent.setup>,
  combobox: string | RegExp,
  option: string | RegExp,
) {
  await user.click(screen.getByRole("combobox", { name: combobox }));
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("UserTypeSelect", () => {
  it("only offers types once a category is chosen", async () => {
    const user = userEvent.setup();
    render(<UserTypeSelect catalog={catalog} value={null} onChange={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: /user type/i })).toBeDisabled();

    await pick(user, /category/i, "Retail");
    const typeSelect = screen.getByRole("combobox", { name: /user type/i });
    expect(typeSelect).toBeEnabled();

    await user.click(typeSelect);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByRole("option", { name: "Agent" })).toBeInTheDocument();
    expect(
      within(listbox).queryByRole("option", { name: "Consumer" }),
    ).not.toBeInTheDocument();
  });

  it("reports the chosen type code to the parent", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UserTypeSelect catalog={catalog} value={null} onChange={onChange} />);

    await pick(user, /category/i, "Retail");
    await pick(user, /user type/i, "Agent");
    expect(onChange).toHaveBeenLastCalledWith("agent");
  });

  it("preselects the category when given an existing value", () => {
    render(<UserTypeSelect catalog={catalog} value="agent" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: /category/i })).toHaveTextContent(
      "Retail",
    );
    expect(screen.getByRole("combobox", { name: /user type/i })).toHaveTextContent(
      "Agent",
    );
  });

  it("clears the chosen type when the category changes", async () => {
    // A type from the old category cannot be legal under the new one, so the
    // picker must not carry it across.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UserTypeSelect catalog={catalog} value="agent" onChange={onChange} />);

    await pick(user, /category/i, "Consumers");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("keeps the new category when the parent clears the type in response", async () => {
    // Changing the category reports onChange(null); a parent that stores the
    // type feeds that back as `value`. The picker must not read its own reset
    // as "narrow to nothing" and disable the type list it just populated.
    function Host() {
      const [value, setValue] = React.useState<string | null>("consumer");
      return <UserTypeSelect catalog={catalog} value={value} onChange={setValue} />;
    }
    const user = userEvent.setup();
    render(<Host />);

    await pick(user, /category/i, "Retail");
    const typeSelect = screen.getByRole("combobox", { name: /user type/i });
    expect(typeSelect).toBeEnabled();

    await user.click(typeSelect);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByRole("option", { name: "Agent" })).toBeInTheDocument();
  });

  it("offers no 'Any' escape hatch when a type is required", () => {
    // Assigning a type to a PERSON has no "all customers" case.
    render(
      <UserTypeSelect catalog={catalog} value={null} onChange={vi.fn()} allowAny={false} />,
    );
    expect(screen.getByRole("combobox", { name: /user type/i })).toBeDisabled();
    expect(screen.queryByText("All customers")).not.toBeInTheDocument();
  });
});
