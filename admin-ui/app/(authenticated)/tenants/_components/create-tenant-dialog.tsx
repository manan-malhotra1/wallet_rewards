"use client";

/**
 * <CreateTenantDialog> — provision a new tenant (platform-admin only).
 *
 * A "New tenant" trigger opens a dialog collecting the tenant's name, business
 * type and base currency, plus OPTIONAL branding (two brand colours + icon
 * URL). The colour controls mirror `branding-dialog.tsx` exactly — a native
 * swatch picker synced to a hex text field — and drive a compact live
 * `brandScale` swatch preview so the admin sees the derived palette before
 * saving. Save calls `createTenantAction`; the backend auto-provisions the
 * new tenant's baseline instruments/services.
 *
 * Client validation blocks submit on an empty name / currency or an invalid
 * hex; the action's revalidation refreshes the tenants list on success.
 */
import * as React from "react";

import { createTenantAction } from "@/app/(authenticated)/tenants/_actions";
import {
  brandScale,
  DEFAULT_ACCENT,
  DEFAULT_LIGHT,
} from "@/lib/brand-palette";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";

/**
 * A 6-digit hex colour — the native `<input type="color">` output and the
 * palette engine both only accept 3/6-digit hex, so we gate on the strict
 * 6-digit subset (matching `branding-dialog.tsx`).
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

/** The seven brand-scale weights, deepest → palest, for the swatch strip. */
const SCALE_WEIGHTS = [900, 800, 600, 500, 400, 200, "050"] as const;

const BUSINESS_TYPES = [
  { value: "wallet", label: "Wallet" },
  { value: "rewards", label: "Rewards" },
  { value: "both", label: "Both" },
] as const;

/**
 * A synced colour control: a native swatch picker plus a hex text field. Both
 * edit the same value; the text field is where an invalid hex can be typed, so
 * validity is surfaced here (mirrors `branding-dialog.tsx`'s ColorField).
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

export function CreateTenantDialog({ trigger }: { trigger: React.ReactNode }) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [businessType, setBusinessType] =
    React.useState<"wallet" | "rewards" | "both">("wallet");
  const [currency, setCurrency] = React.useState("");
  const [accent, setAccent] = React.useState(DEFAULT_ACCENT);
  const [light, setLight] = React.useState(DEFAULT_LIGHT);
  const [iconUrl, setIconUrl] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  // Reset every field to its blank/default whenever the dialog closes, so a
  // cancelled create never leaks into the next open.
  React.useEffect(() => {
    if (!open) {
      setName("");
      setBusinessType("wallet");
      setCurrency("");
      setAccent(DEFAULT_ACCENT);
      setLight(DEFAULT_LIGHT);
      setIconUrl("");
      setError(null);
    }
  }, [open]);

  const nameTrimmed = name.trim();
  const currencyTrimmed = currency.trim();
  const accentValid = HEX_6.test(accent);
  const lightValid = HEX_6.test(light);
  const iconTrimmed = iconUrl.trim();
  const iconValid = iconTrimmed === "" || isHttpUrl(iconTrimmed);
  // Currency is upper-cased server-side; here we only assert 3-10 chars.
  const currencyValid =
    currencyTrimmed.length >= 3 && currencyTrimmed.length <= 10;
  const canSave =
    nameTrimmed !== "" &&
    currencyValid &&
    accentValid &&
    lightValid &&
    iconValid &&
    !submitting;

  // Preview holds the last-valid palette while a hex is mid-edit.
  const previewAccent = accentValid ? accent : DEFAULT_ACCENT;
  const previewLight = lightValid ? light : DEFAULT_LIGHT;
  const scale = brandScale(previewAccent, previewLight);

  async function handleSave() {
    setError(null);
    if (nameTrimmed === "") {
      setError("Tenant name is required.");
      return;
    }
    if (!currencyValid) {
      setError("Base currency must be 3–10 characters.");
      return;
    }
    if (!accentValid || !lightValid) {
      setError("Both brand colours must be valid 6-digit hex.");
      return;
    }
    if (!iconValid) {
      setError("Icon URL must be an http(s) URL.");
      return;
    }
    setSubmitting(true);
    const result = await createTenantAction({
      name: nameTrimmed,
      business_type: businessType,
      base_currency: currencyTrimmed.toUpperCase(),
      brand_accent_color: accent,
      brand_light_color: light,
      brand_icon_url: iconTrimmed === "" ? null : iconTrimmed,
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Tenant created", description: `${nameTrimmed} is ready.` });
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
          <DialogTitle>New tenant</DialogTitle>
          <DialogDescription>
            Provision a tenant. Baseline instruments and services are created
            automatically; branding is optional and can be changed later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label htmlFor="tenant-name">Name</Label>
            <Input
              id="tenant-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
              placeholder="Acme Fintech"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="tenant-business-type">Business type</Label>
              <Select
                value={businessType}
                onValueChange={(v) =>
                  setBusinessType(v as "wallet" | "rewards" | "both")
                }
              >
                <SelectTrigger id="tenant-business-type" className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BUSINESS_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="tenant-currency">Base currency</Label>
              <Input
                id="tenant-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                spellCheck={false}
                maxLength={10}
                aria-invalid={currencyTrimmed !== "" && !currencyValid}
                className="mt-1 font-mono uppercase tabular-nums"
                placeholder="ZAR"
              />
            </div>
          </div>

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
            <Label htmlFor="tenant-icon-url">Icon URL (optional)</Label>
            <Input
              id="tenant-icon-url"
              value={iconUrl}
              onChange={(e) => setIconUrl(e.target.value)}
              spellCheck={false}
              aria-invalid={!iconValid}
              className="mt-1"
              placeholder="https://cdn.example.com/logo.png"
            />
            {!iconValid && (
              <p className="mt-1 text-[11px] text-[--color-danger]">
                Must be an http(s) URL.
              </p>
            )}
          </div>

          <div>
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[--color-text-3]">
              Palette preview
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
          </div>

          {error && <ErrorBanner title="Couldn't create tenant" description={error} />}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!canSave}>
            {submitting ? "Creating…" : "Create tenant"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
