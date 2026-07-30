/**
 * Claymorphism recipe — the single source of truth for the puffy clay look.
 *
 * RN can't render true inset shadows without Skia (not a dependency here), so
 * clay depth is approximated with two ingredients that every clay primitive
 * composes:
 *
 *   1. An OUTER soft drop shadow — a navy `shadow*` tier (iOS) paired with an
 *      Android `elevation` — for the dark shadow below-right.
 *   2. A subtle expo-linear-gradient overlay — a white sheen from the top-left
 *      (`highlight*`) for the raised look, or a downward dark sheen
 *      (`insetShade*`) that makes a surface read pushed-in.
 *
 * Colors are raw hex/rgba (not Tamagui `$tokens`) because expo-linear-gradient
 * consumes plain color strings. The surface fills mirror the `clay*` color
 * tokens in `tamagui.config.ts`; the radii mirror the `clay*` radius tokens.
 */

/** Corner radii for the clay scale (mirror of the `clay*` radius tokens). */
export const clayRadius = { sm: 18, md: 24, lg: 32 } as const;

/** Raised surface drop shadow — the signature soft navy drop, below-right. */
export const shadowRaised = {
  shadowColor: '#012e54',
  shadowOffset: { width: 0, height: 10 },
  shadowRadius: 22,
  shadowOpacity: 0.16,
} as const;

/** Lighter drop for denser surfaces (activity rows, pills, small tiles). */
export const shadowSoft = {
  shadowColor: '#012e54',
  shadowOffset: { width: 0, height: 6 },
  shadowRadius: 14,
  shadowOpacity: 0.12,
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
  bg: '#e8eef5',
  raised: '#f2f6fb',
  inset: '#e9eff6',
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
