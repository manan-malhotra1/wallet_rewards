/**
 * Behaviour tests for BrandingDialog.
 *
 * Covers the admin-facing guarantees: the form seeds from the tenant's current
 * palette, the live preview tracks the accent as it changes, an invalid hex
 * blocks the save, a valid save hands the entered values to the branding
 * action, and a server error surfaces in the dialog. The server action is
 * mocked — the dialog is unit-tested for what it submits, not the backend.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BrandingDialog } from "@/app/(authenticated)/tenants/_components/branding-dialog";
import type { Tenant } from "@/lib/api-types";

const updateTenantBrandingAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/tenants/_actions", () => ({
  updateTenantBrandingAction: (...args: unknown[]) =>
    updateTenantBrandingAction(...args),
}));

/** A tenant already carrying a custom (non-default) palette. */
const tenant: Tenant = {
  id: "tenant-1",
  name: "Acme",
  business_type: "both",
  keycloak_realm: "acme",
  base_currency: "ZAR",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  brand_accent_color: "#112233",
  brand_light_color: "#EEDDCC",
  brand_icon_url: null,
  brand_glass_transparency: null,
};

/** The accent hex text field (its own accessible name from the label). */
function accentHexInput(): HTMLInputElement {
  return screen.getByLabelText("Accent (deep)") as HTMLInputElement;
}

/** The deepest (900) swatch background — the accent anchor of the scale. */
function deepestSwatchColor(): string | undefined {
  const strip = screen.getByLabelText("Brand scale swatches");
  const first = strip.querySelector('[data-weight="900"]') as HTMLElement;
  return first?.style.backgroundColor;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Tenant branding dialog", () => {
  it("Verify the form opens seeded with the tenant's current brand colours", async () => {
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );

    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    expect(accentHexInput().value).toBe("#112233");
    expect((screen.getByLabelText("Light (pale)") as HTMLInputElement).value).toBe(
      "#EEDDCC",
    );
  });

  it("Verify changing the accent updates the live preview swatches", async () => {
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );
    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    const before = deepestSwatchColor();
    expect(before).toBeTruthy();

    const accent = accentHexInput();
    await user.clear(accent);
    await user.type(accent, "#AA0000");

    // The deepest swatch is the accent anchor, so a new accent must repaint it.
    await waitFor(() => {
      const after = deepestSwatchColor();
      expect(after).toBeTruthy();
      expect(after).not.toBe(before);
    });
  });

  it("Verify an invalid hex blocks saving", async () => {
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );
    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    const accent = accentHexInput();
    await user.clear(accent);
    await user.type(accent, "#12"); // too short

    const save = screen.getByRole("button", { name: "Save branding" });
    expect(save).toBeDisabled();
    expect(updateTenantBrandingAction).not.toHaveBeenCalled();
  });

  it("Verify a valid save calls the branding action with the entered values", async () => {
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );
    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    const accent = accentHexInput();
    await user.clear(accent);
    await user.type(accent, "#123456");

    await user.type(
      screen.getByLabelText("Icon URL (optional)"),
      "https://cdn.example.com/logo.png",
    );

    await user.click(screen.getByRole("button", { name: "Save branding" }));

    await waitFor(() =>
      expect(updateTenantBrandingAction).toHaveBeenCalledTimes(1),
    );
    const [tenantId, payload] = updateTenantBrandingAction.mock.calls[0];
    expect(tenantId).toBe("tenant-1");
    expect(payload).toEqual({
      brand_accent_color: "#123456",
      brand_light_color: "#EEDDCC",
      brand_icon_url: "https://cdn.example.com/logo.png",
      brand_glass_transparency: 50,
    });
  });

  it("Verify the transparency slider is present and its value is included in the submitted payload", async () => {
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );
    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    const slider = screen.getByLabelText("Glass transparency") as HTMLInputElement;
    expect(slider).toBeInTheDocument();
    expect(slider.value).toBe("50"); // tenant has no override -> default 50

    fireEvent.change(slider, { target: { value: "80" } });

    await user.click(screen.getByRole("button", { name: "Save branding" }));

    await waitFor(() =>
      expect(updateTenantBrandingAction).toHaveBeenCalledTimes(1),
    );
    const [, payload] = updateTenantBrandingAction.mock.calls[0];
    expect(payload).toMatchObject({ brand_glass_transparency: 80 });
  });

  it("Verify a server error surfaces in the dialog", async () => {
    updateTenantBrandingAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "invalid_hex",
      message: "brand_accent_color failed validation",
    });
    const user = userEvent.setup();
    render(
      <BrandingDialog tenant={tenant} trigger={<button>Customize theme</button>} />,
    );
    await user.click(screen.getByRole("button", { name: "Customize theme" }));

    await user.click(screen.getByRole("button", { name: "Save branding" }));

    await waitFor(() =>
      expect(
        screen.getByText(/invalid_hex: brand_accent_color failed validation/),
      ).toBeInTheDocument(),
    );
  });
});
