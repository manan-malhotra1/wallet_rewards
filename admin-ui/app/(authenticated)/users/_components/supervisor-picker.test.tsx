/**
 * Interaction tests for <SupervisorPicker> from the administrator's chair.
 *
 * Attaching the wrong supervisor misdirects commission, so what these lock in
 * is that the operator confirms a PERSON — name, type, masked phone — before
 * the value is reported upward, that a wrong-type match names the type that
 * was required, and that the optional field can be detached again.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SupervisorPicker } from "@/app/(authenticated)/users/_components/supervisor-picker";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

const lookupUserAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  lookupUserAction: (...args: unknown[]) => lookupUserAction(...args),
}));

beforeEach(() => vi.clearAllMocks());

/** Render the picker wired to a fresh onChange spy. */
function renderPicker() {
  const onChange = vi.fn();
  render(
    <SupervisorPicker
      tenantId="tenant-1"
      catalog={SEED_USER_TYPE_CATALOG}
      requiredType="super_agent"
      value={null}
      onChange={onChange}
    />,
  );
  return { onChange, user: userEvent.setup() };
}

describe("SupervisorPicker", () => {
  it("shows the resolved person for confirmation before attaching", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: {
        id: "u1",
        full_name: "Thabo Nkosi",
        user_type: "super_agent",
        masked_phone: "+2782 *** 0142",
      },
    });
    const { onChange, user } = renderPicker();

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550142");
    await user.click(screen.getByRole("button", { name: /look up/i }));

    expect(await screen.findByText("Thabo Nkosi")).toBeInTheDocument();
    expect(screen.getByText("+2782 *** 0142")).toBeInTheDocument();
    // The phone travels upward, never the resolved id — the backend
    // re-resolves the person when the proposal is approved.
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("+27825550142"));
  });

  it("names the required type when the wrong person is found", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: {
        id: "u2",
        full_name: "Ada Mensah",
        user_type: "consumer",
        masked_phone: "+2782 *** 0199",
      },
    });
    const { onChange, user } = renderPicker();

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550199");
    await user.click(screen.getByRole("button", { name: /look up/i }));

    expect(await screen.findByText(/must be a Super agent/i)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith("+27825550199");
  });

  it("surfaces a failed lookup without attaching anyone", async () => {
    lookupUserAction.mockResolvedValue({
      ok: false,
      errorCode: "user_not_found",
      message: "No user is registered with that phone number.",
    });
    const { onChange, user } = renderPicker();

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825559999");
    await user.click(screen.getByRole("button", { name: /look up/i }));

    expect(
      await screen.findByText("No user is registered with that phone number."),
    ).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("clears an attached supervisor", async () => {
    lookupUserAction.mockResolvedValue({
      ok: true,
      user: {
        id: "u1",
        full_name: "Thabo Nkosi",
        user_type: "super_agent",
        masked_phone: "+2782 *** 0142",
      },
    });
    const { onChange, user } = renderPicker();

    await user.type(screen.getByLabelText(/supervisor's phone/i), "+27825550142");
    await user.click(screen.getByRole("button", { name: /look up/i }));
    await screen.findByText("Thabo Nkosi");

    await user.click(screen.getByRole("button", { name: /clear/i }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
