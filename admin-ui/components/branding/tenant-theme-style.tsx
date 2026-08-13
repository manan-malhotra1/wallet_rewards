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
 * When either colour is missing it renders `null`, so the defaults baked into
 * `globals.css` apply unchanged. The semantic `--destructive` pair is never
 * part of {@link deriveTokens}, so status colours stay constant across tenants.
 */
import * as React from "react";

import { deriveTokens, type TokenMap } from "@/lib/brand-palette";
import { deriveGlassTokens, glassVarsCss } from "@/lib/glass-tokens";

interface TenantThemeStyleProps {
  /** The tenant's deep brand accent hex, or null when unset. */
  accent: string | null;
  /** The tenant's pale brand companion hex, or null when unset. */
  light: string | null;
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
}: TenantThemeStyleProps): React.ReactElement | null {
  // Both colours are required — a partial palette would derive half a theme.
  if (!accent || !light) return null;

  const { light: lightTokens, dark: darkTokens } = deriveTokens(accent, light);
  const glass = deriveGlassTokens(accent, light);
  const css =
    `:root{${toCssVars(lightTokens)}${glassVarsCss(glass.light)}}` +
    `.dark{${toCssVars(darkTokens)}${glassVarsCss(glass.dark)}}`;

  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}
