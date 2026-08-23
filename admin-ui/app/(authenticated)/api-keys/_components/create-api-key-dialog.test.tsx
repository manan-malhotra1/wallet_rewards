/**
 * Interaction tests for CreateApiKeyDialog from the admin operator's chair.
 *
 * These drive the real dialog the way an admin does — open it, optionally look
 * up and bind a merchant, then mint the key — and assert the outcomes the admin
 * cares about: a standard partner key is minted and its one-time secret is
 * revealed, a merchant key binds the resolved user_id, a non-merchant lookup
 * blocks the mint, and a backend rejection is surfaced inline. Both server
 * actions on the route are mocked; no backend is touched. The secret used in
 * these tests is a fabricated placeholder, never a real credential.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateApiKeyDialog } from "@/app/(authenticated)/api-keys/_components/create-api-key-dialog";
import { SEED_USER_TYPE_CATALOG } from "@/lib/__fixtures__/user-type-catalog";

const createApiKeyAction = vi.fn();
const resolveMerchantAction = vi.fn();
vi.mock("@/app/(authenticated)/api-keys/_actions", () => ({
  createApiKeyAction: (...args: unknown[]) => createApiKeyAction(...args),
  resolveMerchantAction: (...args: unknown[]) => resolveMerchantAction(...args),
}));

/** A fabricated created-key payload — the secret is a placeholder, not real. */
const createdKey = {
  id: "key-pk-1",
  tenant_id: "tenant-1",
  key_id: "ak_live_abc123",
  label: null,
  status: "active",
  last_used_at: null,
  created_at: "2026-07-25T00:00:00Z",
  merchant_user_id: null,
  secret: "sk_test_PLACEHOLDER_do_not_use_0000",
};

/** Open the dialog and return the configured userEvent instance. */
async function openDialog() {
  const user = userEvent.setup();
  render(
    <CreateApiKeyDialog
      tenantId="tenant-1"
      catalog={SEED_USER_TYPE_CATALOG}
      trigger={<button type="button">New API key</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New API key" }));
  await screen.findByRole("dialog");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Create an API key", () => {
  it("Verify an admin can mint a partner API key and see its one-time secret", async () => {
    createApiKeyAction.mockResolvedValue({ ok: true, key: createdKey });
    const user = await openDialog();

    await user.type(screen.getByLabelText("Label (optional)"), "partner-acme");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createApiKeyAction).toHaveBeenCalledTimes(1));
    expect(createApiKeyAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      label: "partner-acme",
      merchant_user_id: null,
    });
    // The secret is revealed exactly once for the admin to copy.
    expect(await screen.findByText(createdKey.secret)).toBeInTheDocument();
    expect(screen.getByText(createdKey.key_id)).toBeInTheDocument();
  });

  it("Verify an admin can bind a merchant so the key can call cash-in", async () => {
    resolveMerchantAction.mockResolvedValue({
      ok: true,
      user_id: "usr-merchant-9",
      name: "Acme Stores",
      user_type: "merchant",
    });
    createApiKeyAction.mockResolvedValue({
      ok: true,
      key: { ...createdKey, merchant_user_id: "usr-merchant-9" },
    });
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.click(screen.getByRole("button", { name: "Look up" }));

    // The resolved merchant is confirmed on screen before binding.
    expect(await screen.findByText("Acme Stores")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createApiKeyAction).toHaveBeenCalledTimes(1));
    expect(createApiKeyAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      label: undefined,
      merchant_user_id: "usr-merchant-9",
    });
  });

  it("Verify minting is blocked when the looked-up user is not a merchant", async () => {
    resolveMerchantAction.mockResolvedValue({
      ok: true,
      user_id: "usr-consumer-3",
      name: "Jane Doe",
      user_type: "consumer",
    });
    const user = await openDialog();

    await user.type(screen.getByPlaceholderText("+27 82 555 0001"), "+27 82 555 0001");
    await user.click(screen.getByRole("button", { name: "Look up" }));

    expect(await screen.findByText(/is a consumer, not a merchant/)).toBeInTheDocument();
    // The Create button is disabled while a non-merchant is bound.
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await user.click(create);
    expect(createApiKeyAction).not.toHaveBeenCalled();
  });

  it("Verify a failed key creation shows the error to the admin", async () => {
    createApiKeyAction.mockResolvedValue({
      ok: false,
      errorCode: "rate_limited",
      message: "Too many keys minted recently. Try again later.",
    });
    const user = await openDialog();

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/rate_limited: Too many keys minted recently/),
    ).toBeInTheDocument();
    // The dialog stays open so the admin can retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
