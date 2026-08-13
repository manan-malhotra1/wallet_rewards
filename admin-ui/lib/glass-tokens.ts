/**
 * Glassmorphism token generator.
 *
 * Derives the per-tenant frosted-glass design tokens — atmosphere gradients,
 * panel/overlay tints, hairline borders, and backdrop blur radii — from the
 * same two brand colours (`accent`/`light`) that {@link ../brand-palette.ts}
 * uses for the shadcn theme. See the glassmorphism design spec:
 * `docs/superpowers/specs/2026-08-13-glassmorphism-admin-ui-design.md` §2.
 *
 * Pure TypeScript: no React, no backend, no third-party dependencies.
 */
import { ramp, darken, hexToRgba, DEFAULT_ACCENT, DEFAULT_LIGHT } from "./brand-palette";

/** Backdrop blur radius for in-flow panel surfaces (spec cap: 20px). */
const PANEL_BLUR = "14px";

/** Backdrop blur radius for floating overlay surfaces (spec cap: 20px). */
const OVERLAY_BLUR = "18px";

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
    },
    light: {
      atmosphereImage: blobs(0.22, 0.14, 0.1),
      atmosphereBase: ramp(accent, light, 0.96),
      panel: "rgba(255, 255, 255, 0.55)",
      overlay: "rgba(255, 255, 255, 0.8)",
      border: "rgba(255, 255, 255, 0.75)",
      blurPanel: PANEL_BLUR,
      blurOverlay: OVERLAY_BLUR,
    },
  };
}
