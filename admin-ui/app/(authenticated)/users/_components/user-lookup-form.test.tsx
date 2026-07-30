/**
 * Interaction tests for <UserLookupForm> — the Users-page search controls.
 *
 * The form does not call a server action; it navigates to
 * /users?type=…&value=… so the page server component resolves the customer.
 * These tests drive it as an admin would (pick an identifier, type a value,
 * press Lookup) and assert the navigation the page relies on — including the
 * phone-number canonicalisation that lets a pasted "+27 82 555 0142" resolve.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserLookupForm } from "@/app/(authenticated)/users/_components/user-lookup-form";

// The form's only side effect is a client-side navigation.
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Managing customers — customer lookup", () => {
  it("Verify an admin can look up a customer by phone number", async () => {
    const user = userEvent.setup();
    render(<UserLookupForm initialType="phone" initialValue="" />);

    // An operator pastes a spaced, human-formatted number.
    await user.type(screen.getByLabelText("Value"), "+27 82 555 0142");
    await user.click(screen.getByRole("button", { name: "Lookup" }));

    // Whitespace/punctuation is stripped so the stored canonical number resolves.
    expect(push).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/users?type=phone&value=%2B27825550142");
  });

  it("Verify an admin can look up a customer by email address", async () => {
    const user = userEvent.setup();
    render(<UserLookupForm initialType="email" initialValue="" />);

    await user.type(screen.getByLabelText("Value"), "jane@example.com");
    await user.click(screen.getByRole("button", { name: "Lookup" }));

    // Non-phone identifiers pass through untouched (only trimmed).
    expect(push).toHaveBeenCalledWith("/users?type=email&value=jane%40example.com");
  });

  it("Verify a blank lookup does nothing until an identifier is entered", async () => {
    const user = userEvent.setup();
    render(<UserLookupForm initialType="phone" initialValue="   " />);

    await user.click(screen.getByRole("button", { name: "Lookup" }));

    // An empty/whitespace value must not navigate anywhere.
    expect(push).not.toHaveBeenCalled();
  });
});
