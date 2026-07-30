/**
 * Tamagui configuration for the Sasai Pay mobile app.
 *
 * Locked to the brand palette from the Sasai Pay design system:
 *
 *   - Navy gradient `#00538f → #013a6b` is the signature hero treatment
 *     (the `GradientHeader` component owns the actual gradient render).
 *   - Primary CTA / accent text: `#00508F`.
 *   - Teal range `#50C0D0 / #2EB6C8` is used for sparingly placed accents
 *     (points pill, sub-logo "pay", swoosh outlines on the gradient).
 *   - Surfaces stay near-white (`#f4f7fa` background, `#fff` card, `#f8fafc`
 *     input fill) so the navy/teal pop.
 *   - Status colors are reserved for receipts: `#0a8a5f → #067a52` for the
 *     success header, `#c0392b → #a52e22` for the failed-receipt header.
 *
 * The app also ships a **claymorphism** surface language layered on top of
 * the brand palette: soft cool off-white surfaces, big rounded corners, and a
 * puffy dual-shadow look (dark navy drop below-right + a white highlight sheen
 * above-left). The `clay*` color tokens and the `clay*` radius tokens below are
 * the theme half of that recipe; the shadow + gradient half lives in
 * `components/clay/recipe.ts` (raw values are mirrored there because
 * expo-linear-gradient can't consume Tamagui `$tokens`). Screens compose the
 * look through the primitives in `components/clay/`.
 *
 * `defaultTheme="light"` is locked at the root — every screen is authored
 * against the light surface.
 */
import { config as v3 } from '@tamagui/config/v3';
import { createTamagui } from 'tamagui';

const brand = {
  // Hero gradient stops — referenced as named tokens so a future palette
  // refresh only needs to change them in one place.
  navyTop: '#00538f',
  navyBot: '#013a6b',
  navyDeep: '#012e54',

  // Primary CTA + accent text. Slightly lighter than `navyTop` so it reads
  // well on white as well as in the hero.
  primary: '#00508F',

  // Teal accent family. `tealMid` is the canonical accent the swoosh
  // logo uses; `tealLight` is reserved for ghost-on-navy text contexts.
  tealLight: '#9fd9e2',
  tealMid: '#50C0D0',
  tealDeep: '#2EB6C8',

  // Text + neutral grays.
  ink: '#0c1b2a',
  inkMuted: '#3a4756',
  muted: '#6a7888',
  mutedSoft: '#8a98a6',
  mutedSofter: '#9aa7b5',

  // Surfaces.
  appBg: '#f4f7fa',
  card: '#ffffff',
  inputBg: '#f8fafc',
  border: '#e2e8ef',
  borderSoft: '#eef2f6',
  divider: '#f1f4f7',

  // Status. Used by receipts + activity row amounts.
  successText: '#1aa06b',
  successTop: '#0a8a5f',
  successBot: '#067a52',
  errorText: '#c0392b',
  errorTop: '#c0392b',
  errorBot: '#a52e22',
  warnText: '#c98a00',

  // ─── Claymorphism surfaces ──────────────────────────────────────────────
  // Soft cool off-white app background (the clay "table" everything sits on),
  // the raised clay surface (cards, keys, tiles), and the recessed inset fill
  // (amount displays, sunken fields).
  clayBg: '#ccd8e8',
  claySurface: '#f2f6fb',
  clayInset: '#e9eff6',

  // Clay depth cues. `clayShadowDark` is the navy drop shadow (below-right);
  // `clayHighlight` is the white sheen (above-left); `clayRimLight` is the
  // hairline light top border that finishes the raised edge.
  clayShadowDark: 'rgba(1,46,84,0.20)',
  clayHighlight: 'rgba(255,255,255,0.95)',
  clayRimLight: 'rgba(255,255,255,0.85)',
  clayRimShade: 'rgba(1,46,84,0.06)',
} as const;

/**
 * Clay corner radii — the big-rounded scale the claymorphism language uses.
 * Mirrored as numeric constants in `components/clay/recipe.ts` for the
 * primitives (which also feed the value to expo-linear-gradient overlays so
 * their corners clip to match the surface).
 */
const clayRadius = {
  claySm: 18,
  clay: 24,
  clayLg: 32,
} as const;

export const tamaguiConfig = createTamagui({
  ...v3,
  tokens: {
    ...v3.tokens,
    color: {
      ...v3.tokens.color,
      ...brand,
    },
    radius: {
      ...v3.tokens.radius,
      ...clayRadius,
    },
  },
});

export type AppConfig = typeof tamaguiConfig;

declare module 'tamagui' {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface TamaguiCustomConfig extends AppConfig {}
}

export default tamaguiConfig;
