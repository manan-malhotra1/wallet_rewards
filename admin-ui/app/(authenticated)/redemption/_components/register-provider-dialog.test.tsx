/**
 * Interaction tests for RegisterProviderDialog from the admin operator's chair.
 *
 * An admin registers a cash-out / voucher redemption provider. These drive the
 * real form — fill it, submit — and assert the outcomes the admin cares about:
 * a provider is registered with the entered name and the retry defaults, the
 * name is required, a too-short HMAC secret is refused, and a backend rejection
 * is surfaced. The route's server action is mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterProviderDialog } from "@/app/(authenticated)/redemption/_components/register-provider-dialog";

const registerProviderAction = vi.fn();
vi.mock("@/app/(authenticated)/redemption/_actions", () => ({
  registerProviderAction: (...args: unknown[]) => registerProviderAction(...args),
}));

async function openDialog() {
  const user = userEvent.setup();
  render(
    <RegisterProviderDialog
      tenantId="tenant-1"
      trigger={<button type="button">Register provider</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Register provider" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Register a redemption provider", () => {
  it("Verify an admin can register an airtime redemption provider", async () => {
    registerProviderAction.mockResolvedValue({ ok: true, providerId: "prov-1" });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Mukuru Voucher");
    await user.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(registerProviderAction).toHaveBeenCalledTimes(1));
    expect(registerProviderAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "tenant-1",
      name: "Mukuru Voucher",
      max_retries: 3,
      retry_interval_secs: 300,
      escalate_after_mins: 60,
    });
    // A successful registration closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify registration is blocked when the provider name is missing", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText("Provider name is required.")).toBeInTheDocument();
    expect(registerProviderAction).not.toHaveBeenCalled();
  });

  it("Verify a too-short HMAC secret is refused before anything is sent", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Mukuru Voucher");
    await user.type(screen.getByLabelText(/HMAC shared secret/), "too-short");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText("Shared secret must be at least 32 characters."),
    ).toBeInTheDocument();
    expect(registerProviderAction).not.toHaveBeenCalled();
  });

  it("Verify a failed provider registration shows the error to the admin", async () => {
    registerProviderAction.mockResolvedValue({
      ok: false,
      errorCode: "provider_name_taken",
      message: "A provider with that name is already registered.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Mukuru Voucher");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText(/provider_name_taken: A provider with that name/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
