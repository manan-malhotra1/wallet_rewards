/**
 * Interaction tests for RegisterEventSourceDialog from the admin operator's chair.
 *
 * An admin registers an external system that will publish reward-triggering
 * events. These drive the real form — fill it, submit — and assert the outcomes
 * the admin cares about: a source is registered with the entered details, the
 * required fields are enforced before anything is sent, malformed field-mapping
 * JSON and a too-short HMAC secret are refused, and a backend rejection is
 * surfaced. The route's server action is mocked; no backend is touched.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterEventSourceDialog } from "@/app/(authenticated)/events/_components/register-event-source-dialog";

const registerEventSourceAction = vi.fn();
vi.mock("@/app/(authenticated)/events/_actions", () => ({
  registerEventSourceAction: (...args: unknown[]) => registerEventSourceAction(...args),
}));

async function openDialog() {
  const user = userEvent.setup();
  render(
    <RegisterEventSourceDialog
      tenantId="tenant-1"
      trigger={<button type="button">Register source</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "Register source" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Register an event source", () => {
  it("Verify an admin can register an external event source", async () => {
    registerEventSourceAction.mockResolvedValue({ ok: true, sourceId: "src-1" });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Sasai Bill Pay");
    await user.type(
      screen.getByLabelText("Source key (globally unique)"),
      "sasai-bill-pay-za",
    );
    await user.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(registerEventSourceAction).toHaveBeenCalledTimes(1));
    expect(registerEventSourceAction.mock.calls[0][0]).toMatchObject({
      tenant_id: "tenant-1",
      name: "Sasai Bill Pay",
      source_key: "sasai-bill-pay-za",
    });
    // A successful registration closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify registration is blocked when the name and source key are missing", async () => {
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText("Name and source_key are required."),
    ).toBeInTheDocument();
    expect(registerEventSourceAction).not.toHaveBeenCalled();
  });

  it("Verify a malformed field mapping is refused before anything is sent", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Sasai Bill Pay");
    await user.type(
      screen.getByLabelText("Source key (globally unique)"),
      "sasai-bill-pay-za",
    );
    // `{{` types a single literal "{" — userEvent treats a lone "{" as key syntax.
    await user.type(screen.getByLabelText("Field mapping (JSON, optional)"), "{{not json");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByText("Field mapping must be valid JSON.")).toBeInTheDocument();
    expect(registerEventSourceAction).not.toHaveBeenCalled();
  });

  it("Verify a too-short HMAC secret is refused before anything is sent", async () => {
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Sasai Bill Pay");
    await user.type(
      screen.getByLabelText("Source key (globally unique)"),
      "sasai-bill-pay-za",
    );
    await user.type(screen.getByLabelText(/HMAC shared secret/), "too-short");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText("Shared secret must be at least 32 characters."),
    ).toBeInTheDocument();
    expect(registerEventSourceAction).not.toHaveBeenCalled();
  });

  it("Verify a failed registration shows the error to the admin", async () => {
    registerEventSourceAction.mockResolvedValue({
      ok: false,
      errorCode: "source_key_taken",
      message: "That source key is already registered.",
    });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Name"), "Sasai Bill Pay");
    await user.type(
      screen.getByLabelText("Source key (globally unique)"),
      "sasai-bill-pay-za",
    );
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(
      await screen.findByText(/source_key_taken: That source key is already registered/),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
