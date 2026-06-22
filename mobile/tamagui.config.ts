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
} as const;

export const tamaguiConfig = createTamagui({
  ...v3,
  tokens: {
    ...v3.tokens,
    color: {
      ...v3.tokens.color,
      ...brand,
    },
  },
});

export type AppConfig = typeof tamaguiConfig;

declare module 'tamagui' {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type
  interface TamaguiCustomConfig extends AppConfig {}
}

export default tamaguiConfig;
