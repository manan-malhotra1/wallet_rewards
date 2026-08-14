/**
 * <TenantThemeStyle> — server-rendered per-tenant palette override.
 *
 * Given a tenant's two brand colours, derives the full shadcn token set with
 * {@link deriveTokens} and emits a single inline `<style>` that overrides the
 * CSS custom properties for BOTH themes: `:root { … }` for light and
 * `.dark { … }` for dark. It also derives the glassmorphism tokens with
 * {@link deriveGlassTokens} and serialises them with {@link glassVarsCss}
 * (the shared lib helper — keeps this component from re-deriving its own
 * `--glass-*` var list) alongside the palette, so the atmosphere background
 * and `.glass-*` utilities pick up the tenant's brand colours too. Because
 * it is rendered on the server inside the layout, the override ships in the
 * initial HTML — there is no client round trip and therefore no flash of
 * the default palette.
 *
 * `glassTransparency` (0-100, from the tenant's nullable
 * `brand_glass_transparency` column) tunes the `.glass-panel` alpha; a null
 * value is coerced to {@link DEFAULT_TRANSPARENCY}, `deriveGlassTokens`'s
 * default, which reproduces today's static look.
 *
 * When either colour is missing it renders `null`, so the defaults baked into
 * `globals.css` apply unchanged — this same guard means a tenant that has set
 * ONLY `brand_glass_transparency` via the API (no accent/light) gets no
 * override rendered at all; an accepted limitation, since the branding
 * dialog always writes colours alongside the slider. The semantic
 * `--destructive` pair is never part of {@link deriveTokens}, so status
 * colours stay constant across tenants.
 */
import * as React from "react";

import { deriveTokens, type TokenMap } from "@/lib/brand-palette";
import { DEFAULT_TRANSPARENCY, deriveGlassTokens, glassVarsCss } from "@/lib/glass-tokens";

interface TenantThemeStyleProps {
  /** The tenant's deep brand accent hex, or null when unset. */
  accent: string | null;
  /** The tenant's pale brand companion hex, or null when unset. */
  light: string | null;
  /**
   * The tenant's glass-panel transparency slider (0-100), or null/undefined
   * to fall back to {@link DEFAULT_TRANSPARENCY} (today's static look).
   */
  glassTransparency?: number | null;
}

/** Serialise a token map into a CSS declaration block (`--name: value;`). */
function toCssVars(tokens: TokenMap): string {
  return Object.entries(tokens)
    .map(([name, value]) => `--${name}:${value};`)
    .join("");
}

export function TenantThemeStyle({
  accent,
  light,
  glassTransparency,
}: TenantThemeStyleProps): React.ReactElement | null {
  // Both colours are required — a partial palette would derive half a theme.
  if (!accent || !light) return null;

  const { light: lightTokens, dark: darkTokens } = deriveTokens(accent, light);
  const glass = deriveGlassTokens(accent, light, glassTransparency ?? DEFAULT_TRANSPARENCY);
  const css =
    `:root{${toCssVars(lightTokens)}${glassVarsCss(glass.light)}}` +
    `.dark{${toCssVars(darkTokens)}${glassVarsCss(glass.dark)}}`;

  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}
