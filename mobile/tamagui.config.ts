/**
 * Tamagui configuration for the Sasai Wallet mobile app.
 *
 * Re-exports the upstream v3 `config` (tokens, themes, animations, fonts,
 * media queries, shorthands) and *augments* the colour tokens with the
 * Sasai brand palette so any component can reference `$sasaiNavy`,
 * `$ink`, etc. via Tamagui's `$token` notation.
 *
 * Themes "light" and "dark" come from the v3 preset — the root layout
 * picks one with `defaultTheme` based on `useColorScheme()`.
 */
import { config as v3 } from '@tamagui/config/v3';
import { createTamagui } from 'tamagui';

// Sasai brand tokens — keep in sync with admin-ui and the docs PRD §1.
const brand = {
  sasaiNavy: '#144989',
  sasaiTeal: '#48C2CF',
  ink: '#0B1726',
  inkInverse: '#E8F0F8',
  muted: '#6A7682',
  surfaceLt: '#FFFFFF',
  surfaceDk: '#0E1A2B',
  borderLt: '#E5EAF0',
  borderDk: '#1B2A40',
  error: '#EF4444',
  success: '#22C55E',
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
