/**
 * Semantic color palette — the theme-aware color contract every screen consumes.
 *
 * This is the single source of truth for the app's role-based colors in both
 * light and dark mode. Screens must read colors through `useColors()` (or the
 * raw `light`/`dark` objects) rather than hardcoding hex, so a single palette
 * swap re-themes the whole app. The `light` and `dark` objects share EXACTLY the
 * same keys (`Palette`); the light values reproduce the hexes the screens
 * currently hardcode, so migrating a screen onto this layer is byte-neutral in
 * light mode.
 *
 * All values are raw hex / rgba strings (never Tamagui `$tokens`) so they can be
 * fed directly to Skia `<Canvas>`/`<BoxShadow>` and to plain RN style props.
 *
 * The clay neumorphism shadow/gradient recipe is theme-aware separately in
 * `components/clay/recipe.ts`; this file owns the flat semantic roles (text,
 * status, brand, surfaces, lines) that screens paint on top of the clay.
 */
import { useThemePref } from '@/lib/theme';

/**
 * The semantic color roles. Every key here is guaranteed present in both the
 * `light` and `dark` palettes — this shape IS the contract screens migrate onto.
 */
export interface Palette {
  // Surfaces
  /** App screen background (behind the clay). */
  screenBg: string;
  /** Clay base surface fill. */
  clayBg: string;
  /** Raised clay surface fill (cards, buttons, keys). */
  clayRaised: string;
  /** Recessed clay surface fill (inputs, amount display). */
  clayInset: string;
  /** Teal chip / accent background. */
  chipTealBg: string;
  /** Teal chip / accent foreground text. */
  chipTealText: string;

  // Text
  /** Primary ink text. */
  text: string;
  /** Muted secondary text (labels, captions). */
  textMuted: string;
  /** Faint tertiary text (hints, timestamps). */
  textFaint: string;
  /** Text painted on the navy header / dark gradients. */
  textOnDark: string;

  // Brand
  /** Primary brand navy. */
  navy: string;
  /** Deeper navy (gradient end, headers). */
  navyDeep: string;
  /** Brand teal accent. */
  teal: string;

  // Status
  /** Positive / credit / success. */
  success: string;
  /** Negative / error / debit. */
  danger: string;
  /** Caution / pending. */
  warning: string;

  // Lines
  /** Hairline divider / border. */
  hairline: string;
  /** Soft raised rim edge. */
  rim: string;
}

/**
 * Light palette — reproduces the exact hexes the screens hardcode today. Do NOT
 * retune these: light mode must stay visually byte-identical to the authored app.
 */
export const light: Palette = {
  // Surfaces
  screenBg: '#ccd8e8',
  clayBg: '#ccd8e8',
  clayRaised: '#f4f8fd',
  clayInset: '#c6d3e4',
  chipTealBg: '#e6f6f8',
  chipTealText: '#2EB6C8',

  // Text
  text: '#0c1b2a',
  textMuted: '#6a7888',
  textFaint: '#94a2b1',
  textOnDark: '#ffffff',

  // Brand
  navy: '#00508f',
  navyDeep: '#013a6b',
  teal: '#2EB6C8',

  // Status
  success: '#1aa06b',
  danger: '#c0392b',
  warning: '#d99311',

  // Lines
  hairline: 'rgba(1,46,84,0.06)',
  rim: '#e9f1f9',
};

/**
 * Dark palette — a cohesive dark-navy neumorphism tuned to read on a deep
 * surface. Brand hues are lightened so they stay legible on the dark base, and
 * the navy gradient end (`navyDeep`) stays light enough to keep white text
 * readable across the header gradient.
 */
export const dark: Palette = {
  // Surfaces
  screenBg: '#0e1622',
  clayBg: '#0e1622',
  clayRaised: '#1b2636',
  clayInset: '#0b131f',
  chipTealBg: '#123138',
  chipTealText: '#48C2CF',

  // Text
  text: '#e8eef5',
  textMuted: '#9fb0c2',
  textFaint: '#6d7e91',
  textOnDark: '#ffffff',

  // Brand
  navy: '#3d92cf',
  navyDeep: '#0b2540',
  teal: '#48C2CF',

  // Status
  success: '#2ecc8f',
  danger: '#ff6b6b',
  warning: '#e6b24d',

  // Lines
  hairline: 'rgba(255,255,255,0.08)',
  rim: '#243247',
};

/** The two palettes keyed by theme mode. */
export const palettes: Record<'light' | 'dark', Palette> = { light, dark };

/**
 * Read the semantic palette for the active theme preference.
 *
 * Returns:
 *   The `Palette` matching `useThemePref().pref` (`light` by default). Raw
 *   hex/rgba values, safe for Skia and RN style props alike.
 */
export function useColors(): Palette {
  const { pref } = useThemePref();
  return palettes[pref];
}
