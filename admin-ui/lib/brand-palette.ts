/**
 * Brand palette generator.
 *
 * Turns a tenant's two brand colours (an `accent` — the deep, saturated brand
 * hue — and a `light` — the pale companion) into the full shadcn/ui design-token
 * set for both the dark (default) and light themes. It also exports the colour
 * primitives (`ramp`, `darken`, `hexToRgba`) that the glassmorphism system in
 * `./glass-tokens.ts` builds on to derive gradient, tint, and blur values for
 * frosted-glass surfaces.
 *
 * The engine works entirely in the OKLab perceptual colour space so that the
 * interpolated ramp reads as evenly spaced to the human eye rather than evenly
 * spaced in gamma-encoded sRGB (which bunches up in the shadows). Stops are
 * placed on a golden-ratio scale for a naturally balanced tonal spread.
 *
 * Pure TypeScript: no React, no backend, no third-party dependencies. Most
 * tokens are derived from {@link ramp}, so a tenant only ever supplies two hex
 * colours and the whole UI re-skins deterministically.
 */

/** A single OKLab colour: perceptual lightness `L` plus opponent axes `a`/`b`. */
interface OKLab {
  /** Perceptual lightness, nominally 0 (black) .. 1 (white). */
  L: number;
  /** Green(−)↔red(+) opponent axis. */
  a: number;
  /** Blue(−)↔yellow(+) opponent axis. */
  b: number;
}

/** A linear-light sRGB triple with channels nominally in [0, 1]. */
interface LinearRGB {
  r: number;
  g: number;
  b: number;
}

/**
 * Clamp a number to the inclusive range `[lo, hi]`.
 *
 * @param x - value to clamp
 * @param lo - lower bound (default 0)
 * @param hi - upper bound (default 1)
 * @returns `x` constrained to `[lo, hi]`
 */
function clamp(x: number, lo = 0, hi = 1): number {
  return x < lo ? lo : x > hi ? hi : x;
}

/**
 * Clamp a gamma-encoded [0, 1] channel and scale it to a rounded 0..255 byte.
 * Shared by every hex/rgba string formatter so channel rounding stays consistent.
 *
 * @param v - a channel value, nominally in [0, 1]
 * @returns the channel as an integer in [0, 255]
 */
function to255(v: number): number {
  return Math.round(clamp(v) * 255);
}

/**
 * Parse a `#RGB` or `#RRGGBB` hex string into sRGB channels in [0, 1].
 *
 * @param hex - a hex colour, with or without a leading `#`
 * @returns the three gamma-encoded sRGB channels, each in [0, 1]
 * @throws if the string is not a valid 3- or 6-digit hex colour
 */
export function hexToSrgb(hex: string): { r: number; g: number; b: number } {
  const clean = hex.trim().replace(/^#/, "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((c) => c + c)
          .join("")
      : clean;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) {
    throw new Error(`Invalid hex colour: "${hex}"`);
  }
  const n = parseInt(full, 16);
  return {
    r: ((n >> 16) & 0xff) / 255,
    g: ((n >> 8) & 0xff) / 255,
    b: (n & 0xff) / 255,
  };
}

/**
 * Format three gamma-encoded sRGB channels (in [0, 1]) as an uppercase
 * `#RRGGBB` string. Channels are clamped to the sRGB gamut and rounded.
 *
 * @param c - sRGB channels, each nominally in [0, 1]
 * @returns an uppercase `#RRGGBB` hex string
 */
export function srgbToHex(c: { r: number; g: number; b: number }): string {
  const hex = (v: number) => to255(v).toString(16).padStart(2, "0");
  return `#${hex(c.r)}${hex(c.g)}${hex(c.b)}`.toUpperCase();
}

/**
 * Decode a single gamma-encoded sRGB channel to linear light.
 *
 * @param c - one gamma-encoded channel in [0, 1]
 * @returns the linear-light value
 */
function srgbToLinearChannel(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/**
 * Encode a single linear-light channel back to gamma-encoded sRGB.
 *
 * @param c - one linear-light channel
 * @returns the gamma-encoded value
 */
function linearToSrgbChannel(c: number): number {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

/**
 * Convert gamma-encoded sRGB channels ([0, 1]) to linear-light sRGB.
 *
 * @param c - gamma-encoded sRGB channels
 * @returns linear-light sRGB channels
 */
function srgbToLinear(c: { r: number; g: number; b: number }): LinearRGB {
  return {
    r: srgbToLinearChannel(c.r),
    g: srgbToLinearChannel(c.g),
    b: srgbToLinearChannel(c.b),
  };
}

/**
 * Convert linear-light sRGB to gamma-encoded sRGB channels.
 *
 * @param c - linear-light sRGB channels
 * @returns gamma-encoded sRGB channels (not yet clamped)
 */
function linearToSrgb(c: LinearRGB): { r: number; g: number; b: number } {
  return {
    r: linearToSrgbChannel(c.r),
    g: linearToSrgbChannel(c.g),
    b: linearToSrgbChannel(c.b),
  };
}

/**
 * Convert linear-light sRGB to OKLab using Björn Ottosson's standard matrices.
 *
 * @param rgb - linear-light sRGB channels
 * @returns the colour in OKLab
 */
function linearToOklab(rgb: LinearRGB): OKLab {
  const { r, g, b } = rgb;

  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;

  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);

  return {
    L: 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_,
    a: 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_,
    b: 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_,
  };
}

/**
 * Convert an OKLab colour back to linear-light sRGB (Ottosson's inverse
 * matrices). The result may lie outside the sRGB gamut; callers clamp on
 * encode.
 *
 * @param lab - a colour in OKLab
 * @returns linear-light sRGB channels (possibly out of gamut)
 */
function oklabToLinear(lab: OKLab): LinearRGB {
  const { L, a, b } = lab;

  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;

  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;

  return {
    r: 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    g: -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    b: -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  };
}

/**
 * Convert a hex colour to OKLab.
 *
 * @param hex - a `#RGB`/`#RRGGBB` colour
 * @returns the colour in OKLab
 */
export function hexToOklab(hex: string): OKLab {
  return linearToOklab(srgbToLinear(hexToSrgb(hex)));
}

/**
 * Convert an OKLab colour to a gamut-clamped `#RRGGBB` hex string.
 *
 * @param lab - a colour in OKLab
 * @returns an uppercase, in-gamut `#RRGGBB` hex string
 */
export function oklabToHex(lab: OKLab): string {
  return srgbToHex(linearToSrgb(oklabToLinear(lab)));
}

/**
 * Interpolate (or extrapolate) between the `accent` and `light` brand colours
 * in OKLab, then clamp the result into the sRGB gamut and return it as hex.
 *
 * `t = 0` yields `accent`, `t = 1` yields `light`. Values of `t < 0`
 * extrapolate past the accent (perceptually darker/more saturated) and `t > 1`
 * extrapolate past light (perceptually lighter). The extrapolation is a linear
 * continuation of the accent→light line in OKLab; the final gamut clamp keeps
 * the output a valid, renderable sRGB colour.
 *
 * @param accent - the deep brand hex colour (the `t = 0` anchor)
 * @param light - the pale brand hex colour (the `t = 1` anchor)
 * @param t - position along the accent→light line (may be < 0 or > 1)
 * @returns the interpolated colour as an in-gamut `#RRGGBB` hex string
 */
export function ramp(accent: string, light: string, t: number): string {
  const a = hexToOklab(accent);
  const b = hexToOklab(light);
  return oklabToHex({
    L: a.L + (b.L - a.L) * t,
    a: a.a + (b.a - a.a) * t,
    b: a.b + (b.b - a.b) * t,
  });
}

/**
 * Darken the accent toward black in OKLab (black is the origin, so this scales
 * every OKLab component by `1 - s`). Used for the dark theme's surfaces: because
 * OKLab is roughly perceptually uniform, scaling toward the origin drops both
 * lightness AND chroma together, so a deep surface stays a calm navy. Deriving
 * these surfaces by extrapolating the accent→light line past the accent (`t < 0`)
 * instead PUSHES chroma up and yields an electric indigo — hence this separate path.
 *
 * @param accent - the deep brand hex colour (`s = 0` returns it unchanged)
 * @param s - darkening amount in [0, 1]; `s = 1` is black
 * @returns the darkened colour as an in-gamut `#RRGGBB` hex string
 */
export function darken(accent: string, s: number): string {
  const a = hexToOklab(accent);
  const k = 1 - s;
  return oklabToHex({ L: a.L * k, a: a.a * k, b: a.b * k });
}

/**
 * The seven golden-ratio stop positions along the accent→light line.
 *
 * Derived from powers of the golden ratio φ ≈ 1.618: the four interior stops
 * are `1/φ⁴, 1/φ³, 1/φ², 1/φ` and the fifth is `φ/2`, framed by the exact
 * endpoints 0 and 1. This yields a tonal ramp that feels evenly balanced to
 * the eye rather than mechanically linear.
 */
export const GOLDEN_STOPS = [0, 0.1459, 0.2361, 0.382, 0.618, 0.809, 1] as const;

/**
 * A tenant brand scale keyed by weight, from the deepest accent (`900`) to the
 * palest light (`050`), sampled at the {@link GOLDEN_STOPS} positions.
 */
export interface BrandScale {
  /** `ramp(0)` — the accent anchor, deepest weight. */
  900: string;
  /** `ramp(0.1459)`. */
  800: string;
  /** `ramp(0.2361)`. */
  600: string;
  /** `ramp(0.382)`. */
  500: string;
  /** `ramp(0.618)`. */
  400: string;
  /** `ramp(0.809)`. */
  200: string;
  /** `ramp(1)` — the light anchor, palest weight. */
  "050": string;
}

/**
 * Build the seven-weight golden-ratio {@link BrandScale} for a tenant's two
 * brand colours.
 *
 * @param accent - the deep brand hex colour
 * @param light - the pale brand hex colour
 * @returns the weighted brand scale (`900`..`050`)
 */
export function brandScale(accent: string, light: string): BrandScale {
  return {
    900: ramp(accent, light, GOLDEN_STOPS[0]),
    800: ramp(accent, light, GOLDEN_STOPS[1]),
    600: ramp(accent, light, GOLDEN_STOPS[2]),
    500: ramp(accent, light, GOLDEN_STOPS[3]),
    400: ramp(accent, light, GOLDEN_STOPS[4]),
    200: ramp(accent, light, GOLDEN_STOPS[5]),
    "050": ramp(accent, light, GOLDEN_STOPS[6]),
  };
}

/** The default Sasai brand accent (deep "Ocean" blue). */
export const DEFAULT_ACCENT = "#0C5888";

/** The default Sasai brand light companion (white). */
export const DEFAULT_LIGHT = "#FFFFFF";

/**
 * Every shadcn/ui CSS-variable name this app themes, excluding the semantic
 * `--destructive` pair which is intentionally left out of brand derivation.
 */
export type TokenKey =
  | "background"
  | "foreground"
  | "card"
  | "card-foreground"
  | "popover"
  | "popover-foreground"
  | "primary"
  | "primary-foreground"
  | "secondary"
  | "secondary-foreground"
  | "muted"
  | "muted-foreground"
  | "accent"
  | "accent-foreground"
  | "border"
  | "input"
  | "ring"
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5"
  | "sidebar"
  | "sidebar-foreground"
  | "sidebar-primary"
  | "sidebar-primary-foreground"
  | "sidebar-accent"
  | "sidebar-accent-foreground"
  | "sidebar-border"
  | "sidebar-ring";

/** A complete set of derived token hex values, keyed by {@link TokenKey}. */
export type TokenMap = Record<TokenKey, string>;

/** The dark (default) and light theme token maps for a tenant. */
export interface DerivedTokens {
  light: TokenMap;
  dark: TokenMap;
}

/**
 * Derive the full dark + light shadcn token set from a tenant's two brand
 * colours.
 *
 * The dark theme darkens the accent toward black for surfaces (see {@link darken})
 * with the light colour as foreground; the light theme anchors surfaces at/above
 * the light colour (via {@link ramp}) with the accent as foreground. `chart-5` is a fixed amber accent (warm counterpoint to
 * the brand hue) in each theme, and the semantic `--destructive` pair is
 * deliberately not produced here — status colours stay constant across tenants.
 *
 * @param accent - the deep brand hex colour (defaults to {@link DEFAULT_ACCENT})
 * @param light - the pale brand hex colour (defaults to {@link DEFAULT_LIGHT})
 * @returns `{ light, dark }` token maps, each a hex value per {@link TokenKey}
 */
export function deriveTokens(
  accent: string = DEFAULT_ACCENT,
  light: string = DEFAULT_LIGHT,
): DerivedTokens {
  const r = (t: number) => ramp(accent, light, t);
  // Dark surfaces darken the accent toward black (keeps the navy calm); dark
  // accents/text sample the accent→light ramp.
  const d = (s: number) => darken(accent, s);

  const dark: TokenMap = {
    background: d(0.55),
    foreground: r(1),
    card: d(0.42),
    "card-foreground": r(1),
    popover: d(0.42),
    "popover-foreground": r(1),
    primary: r(1),
    "primary-foreground": r(0),
    secondary: d(0.3),
    "secondary-foreground": r(1),
    muted: d(0.38),
    "muted-foreground": r(0.618),
    accent: r(0.1459),
    "accent-foreground": r(1),
    border: d(0.3),
    input: d(0.3),
    ring: r(0.382),
    "chart-1": r(1),
    "chart-2": r(0.618),
    "chart-3": r(0.382),
    "chart-4": r(0.236),
    "chart-5": "#E7B24B",
    sidebar: d(0.62),
    "sidebar-foreground": r(1),
    "sidebar-primary": r(1),
    "sidebar-primary-foreground": r(0),
    "sidebar-accent": r(0.1459),
    "sidebar-accent-foreground": r(1),
    "sidebar-border": d(0.46),
    "sidebar-ring": r(0.382),
  };

  const lightTheme: TokenMap = {
    background: r(1),
    foreground: r(-0.15),
    card: r(1.12),
    "card-foreground": r(-0.15),
    popover: r(1.12),
    "popover-foreground": r(-0.15),
    primary: r(0),
    "primary-foreground": r(1),
    secondary: r(0.9),
    "secondary-foreground": r(0),
    muted: r(0.88),
    "muted-foreground": r(0.236),
    accent: r(0.85),
    "accent-foreground": r(0),
    border: r(0.8),
    input: r(0.8),
    ring: r(0.236),
    "chart-1": r(0),
    "chart-2": r(0.236),
    "chart-3": r(0.382),
    "chart-4": r(0.618),
    "chart-5": "#B7791F",
    sidebar: r(0),
    "sidebar-foreground": r(1),
    "sidebar-primary": r(1),
    "sidebar-primary-foreground": r(0),
    "sidebar-accent": r(0.1459),
    "sidebar-accent-foreground": r(1),
    "sidebar-border": r(-0.15),
    "sidebar-ring": r(0.236),
  };

  return { light: lightTheme, dark };
}

/**
 * Convert a hex colour + alpha into an `rgba(r, g, b, a)` CSS string.
 *
 * @param hex - a `#RGB`/`#RRGGBB` colour
 * @param alpha - opacity in [0, 1], emitted verbatim
 * @returns an `rgba(...)` string usable in CSS values
 * @throws if `hex` is not a valid 3- or 6-digit hex colour (propagated from {@link hexToSrgb})
 */
export function hexToRgba(hex: string, alpha: number): string {
  const c = hexToSrgb(hex);
  return `rgba(${to255(c.r)}, ${to255(c.g)}, ${to255(c.b)}, ${alpha})`;
}
