/**
 * Claymorphism recipe — the single source of truth for the puffy clay look.
 *
 * Clay depth is now rendered with `@shopify/react-native-skia`: every primitive
 * paints a rounded `Box` BEHIND its content carrying real inner + outer shadows
 * (see `ClayShape.tsx`). Two families of params drive that:
 *
 *   1. `claySkiaInner` — the INNER shadow pair per depth variant. An inner
 *      near-white highlight + an inner navy depth shadow give the puffy
 *      inflated (raised) look, or the carved-in (pressed / inset) look.
 *   2. `claySkiaDrop` — the OUTER soft navy drop so a raised piece lifts off
 *      the page.
 *
 * IMPORTANT — Skia inner-shadow sign convention. Skia's `BoxShadow inner`
 * fills `box − (box shifted by dx,dy)`, so a POSITIVE `dx,dy` paints the colour
 * on the TOP-LEFT interior edges and a NEGATIVE `dx,dy` paints it on the
 * BOTTOM-RIGHT (this is CSS `inset` box-shadow parity, and the inverse of the
 * offsets you'd write for an OUTER drop). The values below are chosen for the
 * resulting look, not to mirror an outer-shadow's signs.
 *
 * The legacy RN/expo-linear-gradient params below (`shadow*`, `highlight*`,
 * `insetShade*`, gradients) are kept because `recipe.ts` is the shared colour
 * source (e.g. `clay.claySurface.bg` for screen backgrounds).
 *
 * Colors are raw hex/rgba (not Tamagui `$tokens`). The surface fills mirror the
 * `clay*` color tokens in `tamagui.config.ts`; the radii mirror the `clay*`
 * radius tokens.
 */

/** Corner radii for the clay scale (mirror of the `clay*` radius tokens). */
export const clayRadius = { sm: 22, md: 30, lg: 40 } as const;

/**
 * Transparent breathing room (px) added around every clay `Canvas` so the OUTER
 * drop shadow isn't clipped by the canvas bounds. Must exceed the largest drop
 * reach (offset + ~3×blur-sigma). See `ClayShape.tsx`.
 */
export const CLAY_SHADOW_PAD = 72;

/** A single Skia shadow spec (maps to `<BoxShadow>` props). `blur` is a sigma. */
export interface ClaySkiaShadow {
  inner: boolean;
  dx: number;
  dy: number;
  blur: number;
  color: string;
}

/**
 * INNER shadow pairs per depth variant. `highlight` is the near-white inner
 * light, `depth` is the navy inner dark. Signs follow the Skia inner-shadow
 * convention documented above (positive dx,dy ⇒ top-left).
 *
 *   - raised  — light top-left + dark bottom-right ⇒ puffy / inflated.
 *   - pressed — dark top-left + light bottom-right ⇒ pushed-in (keys, buttons).
 *   - inset   — stronger dark top-left + faint light bottom-right ⇒ carved-in.
 */
export const claySkiaInner: Record<
  'raised' | 'pressed' | 'inset',
  { highlight: ClaySkiaShadow; depth: ClaySkiaShadow }
> = {
  raised: {
    highlight: { inner: true, dx: 7, dy: 7, blur: 13, color: 'rgba(255,255,255,0.85)' },
    depth: { inner: true, dx: -7, dy: -7, blur: 15, color: 'rgba(1,46,84,0.28)' },
  },
  pressed: {
    depth: { inner: true, dx: 7, dy: 7, blur: 12, color: 'rgba(1,46,84,0.40)' },
    highlight: { inner: true, dx: -6, dy: -6, blur: 12, color: 'rgba(255,255,255,0.5)' },
  },
  inset: {
    depth: { inner: true, dx: 8, dy: 8, blur: 14, color: 'rgba(1,46,84,0.34)' },
    highlight: { inner: true, dx: -6, dy: -6, blur: 12, color: 'rgba(255,255,255,0.45)' },
  },
} as const;

/**
 * OUTER drop tiers for raised pieces (navy, below-right). `strong` is the
 * primary CTA lift; `raised` is the signature card; `soft` is denser surfaces.
 * `blur` is a sigma — keep offset + ~3×blur under `CLAY_SHADOW_PAD`.
 */
export const claySkiaDrop: Record<'soft' | 'raised' | 'strong', ClaySkiaShadow> = {
  soft: { inner: false, dx: 3, dy: 7, blur: 12, color: 'rgba(1,46,84,0.22)' },
  raised: { inner: false, dx: 4, dy: 9, blur: 15, color: 'rgba(1,46,84,0.26)' },
  strong: { inner: false, dx: 0, dy: 11, blur: 16, color: 'rgba(1,55,107,0.32)' },
} as const;

/** Raised surface drop shadow — the signature soft navy drop, below-right. */
export const shadowRaised = {
  shadowColor: '#012e54',
  shadowOffset: { width: 6, height: 12 },
  shadowRadius: 34,
  shadowOpacity: 0.34,
} as const;

/** Light top-left "shadow" — the clay double-shadow companion. Rendered on a
 * sibling layer behind the surface so white spills up-left while the navy drop
 * spills down-right, giving the puffy inflated clay look RN can't do in one view. */
export const shadowLight = {
  shadowColor: '#ffffff',
  shadowOffset: { width: -8, height: -8 },
  shadowRadius: 22,
  shadowOpacity: 1,
} as const;

/** Lighter drop for denser surfaces (activity rows, pills, small tiles). */
export const shadowSoft = {
  shadowColor: '#012e54',
  shadowOffset: { width: 4, height: 8 },
  shadowRadius: 22,
  shadowOpacity: 0.24,
} as const;

/** Strong drop reserved for the primary navy CTA so it lifts off the page. */
export const shadowStrong = {
  shadowColor: '#013a6b',
  shadowOffset: { width: 0, height: 12 },
  shadowRadius: 22,
  shadowOpacity: 0.26,
} as const;

/** Pressed-in: pull the shadow close + small so the surface reads pushed down. */
export const shadowPressed = {
  shadowColor: '#012e54',
  shadowOffset: { width: 0, height: 2 },
  shadowRadius: 5,
  shadowOpacity: 0.14,
} as const;

/** Android elevation paired with each iOS shadow tier. */
export const elevation = { raised: 8, soft: 5, strong: 12, pressed: 1 } as const;

/** Top-left white sheen for raised clay surfaces. */
export const highlightColors = [
  'rgba(255,255,255,0.9)',
  'rgba(255,255,255,0.25)',
  'rgba(255,255,255,0)',
] as const;
export const highlightLocations = [0, 0.55, 1] as const;
export const highlightStart = { x: 0, y: 0 } as const;
export const highlightEnd = { x: 0.9, y: 1 } as const;

/** Downward dark sheen that makes a surface read recessed / pushed-in. */
export const insetShadeColors = [
  'rgba(1,46,84,0.14)',
  'rgba(1,46,84,0.03)',
  'rgba(1,46,84,0)',
] as const;
export const insetShadeLocations = [0, 0.5, 1] as const;

/** Brand gradients (raw hex — expo-linear-gradient can't take `$tokens`). */
export const navyGradient = ['#00538f', '#013a6b'] as const;
export const tealGradient = ['#50C0D0', '#2EB6C8'] as const;

/** Clay surface fills (mirror of the `clay*` color tokens). */
export const claySurface = {
  bg: '#ccd8e8',
  raised: '#f4f8fd',
  inset: '#c6d3e4',
} as const;

/** Hairline rim colors — the light raised edge and the soft recessed edge. */
export const clayRimLight = 'rgba(255,255,255,0.85)';
export const clayRimShade = 'rgba(1,46,84,0.06)';

/** Absolute-fill style for a rounded gradient overlay clipped to `radius`. */
export function overlayFill(radius: number) {
  return {
    position: 'absolute' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: radius,
  };
}
