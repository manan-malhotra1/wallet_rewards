"use client";

/**
 * <BrandingDialog> — per-tenant cosmetic branding editor (platform-admin only).
 *
 * Lets an admin set a tenant's two brand colours (deep `accent` + pale `light`)
 * and an optional icon URL, with a LIVE palette preview: the seven-stop
 * `brandScale` rendered as swatches, plus a tiny mock UI themed with the actual
 * `deriveTokens(accent, light).dark` map (dark is the app's default theme) so
 * the admin sees the real result before saving.
 *
 * The preview reuses the exact token-override approach of
 * `components/branding/tenant-theme-style.tsx`: the derived shadcn tokens are
 * written as CSS custom properties onto a wrapper, so Tailwind utility classes
 * (`bg-card`, `text-primary-foreground`, …) inside it resolve to the tenant's
 * palette rather than the app's.
 *
 * Save writes directly via `updateTenantBrandingAction` (no maker-checker); the
 * action revalidates the authenticated layout so the whole app re-themes.
 */
import * as React from "react";

import { updateTenantBrandingAction } from "@/app/(authenticated)/tenants/_actions";
import {
  brandScale,
  deriveTokens,
  DEFAULT_ACCENT,
  DEFAULT_LIGHT,
  type TokenMap,
} from "@/lib/brand-palette";
import type { Tenant } from "@/lib/api-types";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";

/**
 * A 6-digit hex colour — the form matches the native `<input type="color">`
 * output and the palette engine's `hexToSrgb`, which only accept 3/6-digit
 * hex. The backend regex is wider (`^#[0-9a-fA-F]{6,8}$`); we stay on the
 * strict subset so the live preview can always derive a full palette.
 */
const HEX_6 = /^#[0-9a-fA-F]{6}$/;

/** True when `url` is a syntactically valid http(s) URL. */
function isHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/** Serialise a token map into inline CSS custom properties for a wrapper. */
function tokenStyle(tokens: TokenMap): React.CSSProperties {
  const style: Record<string, string> = {};
  for (const [name, value] of Object.entries(tokens)) {
    style[`--${name}`] = value;
  }
  return style as React.CSSProperties;
}

/** The seven brand-scale weights, deepest → palest, for the swatch strip. */
const SCALE_WEIGHTS = [900, 800, 600, 500, 400, 200, "050"] as const;

/**
 * A synced colour control: a native swatch picker plus a hex text field. Both
 * edit the same value; the text field is where an invalid hex can be typed, so
 * validity is surfaced here and lifted to the parent for the save gate.
 */
function ColorField({
  id,
  label,
  value,
  onChange,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  invalid: boolean;
}) {
  return (
    <div>
      <Label htmlFor={`${id}-hex`}>{label}</Label>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} colour picker`}
          // The native picker only speaks lowercase 6-digit hex; normalise the
          // current value so it never throws on an in-progress text edit.
          value={HEX_6.test(value) ? value.toLowerCase() : "#000000"}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-9 w-12 shrink-0 cursor-pointer rounded-md border border-input bg-background p-1"
        />
        <Input
          id={`${id}-hex`}
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          spellCheck={false}
          maxLength={7}
          aria-invalid={invalid}
          className="font-mono uppercase tabular-nums"
          placeholder="#243B8F"
        />
      </div>
      {invalid && (
        <p className="mt-1 text-[11px] text-[--color-danger]">
          Enter a 6-digit hex colour, e.g. #243B8F.
        </p>
      )}
    </div>
  );
}

export function BrandingDialog({
  tenant,
  trigger,
}: {
  tenant: Tenant;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [accent, setAccent] = React.useState(
    tenant.brand_accent_color ?? DEFAULT_ACCENT,
  );
  const [light, setLight] = React.useState(
    tenant.brand_light_color ?? DEFAULT_LIGHT,
  );
  const [iconUrl, setIconUrl] = React.useState(tenant.brand_icon_url ?? "");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Reset the form to the tenant's persisted values whenever the dialog closes,
  // so a cancelled edit never leaks into the next open.
  React.useEffect(() => {
    if (!open) {
      setAccent(tenant.brand_accent_color ?? DEFAULT_ACCENT);
      setLight(tenant.brand_light_color ?? DEFAULT_LIGHT);
      setIconUrl(tenant.brand_icon_url ?? "");
      setError(null);
    }
  }, [open, tenant]);

  const accentValid = HEX_6.test(accent);
  const lightValid = HEX_6.test(light);
  const iconTrimmed = iconUrl.trim();
  const iconValid = iconTrimmed === "" || isHttpUrl(iconTrimmed);
  const canSave = accentValid && lightValid && iconValid && !submitting;

  // Only derive the preview from a valid palette; while a hex is mid-edit the
  // last-valid swatches simply hold (falling back to defaults if never valid).
  const previewAccent = accentValid ? accent : DEFAULT_ACCENT;
  const previewLight = lightValid ? light : DEFAULT_LIGHT;
  const scale = brandScale(previewAccent, previewLight);
  const darkTokens = deriveTokens(previewAccent, previewLight).dark;

  function handleReset() {
    setAccent(DEFAULT_ACCENT);
    setLight(DEFAULT_LIGHT);
    setError(null);
  }

  async function handleSave() {
    setError(null);
    if (!accentValid || !lightValid) {
      setError("Both brand colours must be valid 6-digit hex.");
      return;
    }
    if (!iconValid) {
      setError("Icon URL must be an http(s) URL.");
      return;
    }
    setSubmitting(true);
    const result = await updateTenantBrandingAction(tenant.id, {
      brand_accent_color: accent,
      brand_light_color: light,
      brand_icon_url: iconTrimmed === "" ? null : iconTrimmed,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Branding saved", description: `${tenant.name} re-themed.` });
      setOpen(false);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Customize theme</DialogTitle>
          <DialogDescription>
            Set {tenant.name}&apos;s two brand colours and icon. The palette is
            derived live — what you see below is the saved result.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <ColorField
              id="accent"
              label="Accent (deep)"
              value={accent}
              onChange={setAccent}
              invalid={!accentValid}
            />
            <ColorField
              id="light"
              label="Light (pale)"
              value={light}
              onChange={setLight}
              invalid={!lightValid}
            />
          </div>

          <div>
            <Label htmlFor="brand-icon-url">Icon URL (optional)</Label>
            <div className="mt-1 flex items-center gap-2">
              <Input
                id="brand-icon-url"
                value={iconUrl}
                onChange={(e) => setIconUrl(e.target.value)}
                spellCheck={false}
                aria-invalid={!iconValid}
                placeholder="https://cdn.example.com/logo.png"
              />
              {iconValid && iconTrimmed !== "" && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={iconTrimmed}
                  alt="Icon preview"
                  className="h-9 w-9 shrink-0 rounded-md border border-input object-contain"
                />
              )}
            </div>
            {!iconValid && (
              <p className="mt-1 text-[11px] text-[--color-danger]">
                Must be an http(s) URL.
              </p>
            )}
          </div>

          <div>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
              Live preview
            </div>
            <div
              aria-label="Brand scale swatches"
              className="flex overflow-hidden rounded-md border border-input"
            >
              {SCALE_WEIGHTS.map((weight) => (
                <div
                  key={weight}
                  title={`${weight}: ${scale[weight]}`}
                  data-weight={weight}
                  className="h-8 flex-1"
                  style={{ backgroundColor: scale[weight] }}
                />
              ))}
            </div>

            {/* Mock UI themed with the tenant's dark-theme tokens (the app's
                default theme), so the admin previews the actual result. */}
            <div
              data-testid="brand-preview-mock"
              style={tokenStyle(darkTokens)}
              className="mt-3 rounded-lg border border-border bg-card p-4 text-card-foreground"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold">Card title</div>
                <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] font-medium text-primary-foreground">
                  Active
                </span>
              </div>
              <div className="mt-1 text-[12px] text-muted-foreground">
                A muted supporting line of text.
              </div>
              <div className="mt-3 h-px w-full bg-border" />
              <button
                type="button"
                className="mt-3 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground"
              >
                Primary action
              </button>
            </div>
          </div>

          {error && <ErrorBanner title="Couldn't save branding" description={error} />}
        </div>

        <DialogFooter className="sm:justify-between">
          <Button variant="ghost" onClick={handleReset} disabled={submitting}>
            Reset to default
          </Button>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={!canSave}>
              {submitting ? "Saving…" : "Save branding"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
