/**
 * Interaction tests for <AuditFilters> — the audit-log narrowing controls.
 *
 * The form has no server action; it navigates to /audit?entity_type=…&entity_id=…
 * so the page server component re-fetches the filtered slice. These tests drive
 * it as a compliance admin would (type an entity type and/or id, press Filter,
 * or press Clear) and assert the navigation the page relies on.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuditFilters } from "@/app/(authenticated)/audit/_components/audit-filters";

// The form's only side effect is a client-side navigation.
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Audit log — filtering", () => {
  it("Verify an admin can filter the audit log by entity type", async () => {
    const user = userEvent.setup();
    render(<AuditFilters initialEntityType="" initialEntityId="" />);

    await user.type(screen.getByLabelText("Entity type"), "redemption");
    await user.click(screen.getByRole("button", { name: "Filter" }));

    // Only the populated field is carried into the query string.
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/audit?entity_type=redemption");
  });

  it("Verify an admin can filter the audit log by entity type and ID together", async () => {
    const user = userEvent.setup();
    render(<AuditFilters initialEntityType="" initialEntityId="" />);

    await user.type(screen.getByLabelText("Entity type"), "redemption");
    await user.type(screen.getByLabelText("Entity ID"), "abc-123");
    await user.click(screen.getByRole("button", { name: "Filter" }));

    expect(push).toHaveBeenCalledWith("/audit?entity_type=redemption&entity_id=abc-123");
  });

  it("Verify an admin can clear the audit log filters", async () => {
    const user = userEvent.setup();
    render(<AuditFilters initialEntityType="redemption" initialEntityId="abc-123" />);

    await user.click(screen.getByRole("button", { name: "Clear" }));

    // Clear discards both fields and returns to the unfiltered list.
    expect(push).toHaveBeenCalledWith("/audit");
    expect(screen.getByLabelText("Entity type")).toHaveValue("");
    expect(screen.getByLabelText("Entity ID")).toHaveValue("");
  });
});
