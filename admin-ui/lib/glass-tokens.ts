/**
 * Glassmorphism token generator.
 *
 * Derives the per-tenant frosted-glass design tokens — atmosphere gradients,
 * panel/overlay tints, hairline borders, backdrop blur radii, and elevation
 * shadows — from the same two brand colours (`accent`/`light`) that
 * `./brand-palette` uses for the shadcn theme. See the glassmorphism design
 * spec: `docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md`
 * §2.
 *
 * `admin-ui/app/globals.css` bakes the Ocean defaults (`deriveGlassTokens(
 * DEFAULT_ACCENT, DEFAULT_LIGHT)`) into `:root`/`.dark` as static values —
 * `glass-tokens.test.ts` has a sync-guard test that reads that file and
 * fails if it drifts from this function's output.
 *
 * Pure TypeScript: no React, no backend, no third-party dependencies.
 */
import { ramp, darken, hexToRgba, DEFAULT_ACCENT, DEFAULT_LIGHT } from "./brand-palette";

/** Backdrop blur radius for in-flow panel surfaces (spec cap: 20px). */
const PANEL_BLUR = "14px";

/** Backdrop blur radius for floating overlay surfaces (spec cap: 20px). */
const OVERLAY_BLUR = "18px";

/** Elevation shadow for `.glass-panel` — identical across schemes (spec §3). */
const PANEL_SHADOW = "inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 6px 22px rgba(0, 0, 0, 0.25)";

/** Elevation shadow for `.glass-overlay` — identical across schemes (spec §3). */
const OVERLAY_SHADOW = "inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 16px 48px rgba(0, 0, 0, 0.45)";

/** The glass design tokens for one colour scheme (see the glassmorphism spec). */
export interface GlassTokens {
  /** Comma-joined radial gradients — the atmosphere `background-image`. */
  atmosphereImage: string;
  /** Hex base colour painted under the gradient blobs (`background-color`). */
  atmosphereBase: string;
  /** Panel tint for in-flow surfaces (`.glass-panel`). */
  panel: string;
  /** Higher-opacity tint for floating surfaces (`.glass-overlay`). */
  overlay: string;
  /** Hairline border colour shared by all glass surfaces. */
  border: string;
  /** Backdrop blur radius for panels, e.g. `"14px"`. */
  blurPanel: string;
  /** Backdrop blur radius for overlays, e.g. `"18px"` (spec cap: 20px). */
  blurOverlay: string;
  /** `box-shadow` value for `.glass-panel` (inset highlight + drop shadow). */
  shadowPanel: string;
  /** `box-shadow` value for `.glass-overlay` (inset highlight + drop shadow). */
  shadowOverlay: string;
}

/**
 * Maps every {@link GlassTokens} field to its CSS custom-property name.
 *
 * Single source of truth for the field ↔ `--glass-*` name pairing: adding a
 * field to {@link GlassTokens} without adding it here is a TypeScript error
 * (`Record<keyof GlassTokens, string>` demands total coverage), so the CSS
 * emission in {@link glassVarsCss} can never silently drop a token.
 */
export const GLASS_VAR_NAMES: Record<keyof GlassTokens, string> = {
  atmosphereImage: "glass-atmosphere-image",
  atmosphereBase: "glass-atmosphere-base",
  panel: "glass-panel",
  overlay: "glass-overlay",
  border: "glass-border",
  blurPanel: "glass-blur-panel",
  blurOverlay: "glass-blur-overlay",
  shadowPanel: "glass-shadow-panel",
  shadowOverlay: "glass-shadow-overlay",
};

/**
 * Serialise one scheme's glass tokens into `--name:value;` CSS custom
 * property declarations, in {@link GLASS_VAR_NAMES} order.
 *
 * Single consumer: `TenantThemeStyle`'s per-tenant inline `<style>` override
 * (the same job `toCssVars` does there for the palette tokens). The static
 * Ocean defaults baked into `globals.css` are NOT produced by this function —
 * they're hand-written CSS kept in sync by a separate sync-guard test in
 * `glass-tokens.test.ts`, which compares `deriveGlassTokens()`'s output
 * directly against `globals.css`'s text.
 *
 * @param tokens - one scheme's derived glass tokens
 * @returns a concatenated string of `--glass-*:value;` declarations
 */
export function glassVarsCss(tokens: GlassTokens): string {
  return (Object.keys(GLASS_VAR_NAMES) as (keyof GlassTokens)[])
    .map((field) => `--${GLASS_VAR_NAMES[field]}:${tokens[field]};`)
    .join("");
}

/** Dark + light glass token sets for a tenant. */
export interface DerivedGlass {
  light: GlassTokens;
  dark: GlassTokens;
}

/**
 * Derive the glassmorphism token set from a tenant's two brand colours
 * (spec: docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md §2).
 *
 * The atmosphere is three accent-tinted radial blobs (accent, the 0.382 ramp
 * companion, a darkened deep) over a tinted-near-black (dark) / near-white
 * (light) base. Panel/overlay tints are white-frost rgba values; the dark
 * overlay carries the darkened brand hue at high alpha so floating surfaces
 * occlude what's beneath them. Blob alphas stay within the spec bounds
 * (dark ≤ 0.55, light ≤ 0.25) and blur is capped below 20px.
 *
 * @param accent - the deep brand hex colour (defaults to {@link DEFAULT_ACCENT})
 * @param light - the pale brand hex colour (defaults to {@link DEFAULT_LIGHT})
 * @returns `{ light, dark }` glass token sets
 */
export function deriveGlassTokens(
  accent: string = DEFAULT_ACCENT,
  light: string = DEFAULT_LIGHT,
): DerivedGlass {
  const mid = ramp(accent, light, 0.382);
  const deep = darken(accent, 0.25);
  const blobs = (accentA: number, midA: number, deepA: number) =>
    [
      `radial-gradient(ellipse 60% 50% at 15% 10%, ${hexToRgba(accent, accentA)}, transparent 60%)`,
      `radial-gradient(ellipse 50% 45% at 85% 90%, ${hexToRgba(mid, midA)}, transparent 60%)`,
      `radial-gradient(ellipse 45% 40% at 70% 20%, ${hexToRgba(deep, deepA)}, transparent 55%)`,
    ].join(", ");

  return {
    dark: {
      atmosphereImage: blobs(0.5, 0.28, 0.4),
      // 0.62 (not e.g. 0.9) keeps the base a tinted near-black rather than
      // collapsing to brand-invariant pure black (darken(x, 0.9) ≈ #000001
      // for any accent).
      atmosphereBase: darken(accent, 0.62),
      panel: "rgba(255, 255, 255, 0.06)",
      overlay: hexToRgba(darken(accent, 0.55), 0.78),
      border: "rgba(255, 255, 255, 0.12)",
      blurPanel: PANEL_BLUR,
      blurOverlay: OVERLAY_BLUR,
      shadowPanel: PANEL_SHADOW,
      shadowOverlay: OVERLAY_SHADOW,
    },
    light: {
      atmosphereImage: blobs(0.22, 0.14, 0.1),
      atmosphereBase: ramp(accent, light, 0.96),
      panel: "rgba(255, 255, 255, 0.55)",
      overlay: "rgba(255, 255, 255, 0.8)",
      border: "rgba(255, 255, 255, 0.75)",
      blurPanel: PANEL_BLUR,
      blurOverlay: OVERLAY_BLUR,
      shadowPanel: PANEL_SHADOW,
      shadowOverlay: OVERLAY_SHADOW,
    },
  };
}
