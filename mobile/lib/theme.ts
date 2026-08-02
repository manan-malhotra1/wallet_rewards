/**
 * Theme preference store — the app's light/dark toggle state.
 *
 * A tiny React context holding `pref: 'light' | 'dark'` (default 'light'),
 * persisted via the secure-store wrapper in `lib/storage.ts`. The root layout
 * reads `pref` to drive Tamagui's `defaultTheme` + the status-bar style, and
 * the Settings screen flips it via `setPref`.
 *
 * NOTE: full dark styling of every screen is a separate, later effort. This
 * store only owns the preference; hardcoded-color screens won't fully adapt
 * until they're re-themed. See app/settings/index.tsx for the user-facing note.
 */
import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { getThemePref, setThemePref } from '@/lib/storage';

/** The two supported theme preferences. */
export type ThemePref = 'light' | 'dark';

interface ThemeContextValue {
  /** Current preference. Defaults to 'light' until storage resolves. */
  pref: ThemePref;
  /** Set + persist the preference. */
  setPref: (next: ThemePref) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Provider that loads the persisted theme preference on mount and exposes it
 * (plus a persisting setter) to the tree.
 *
 * Must sit ABOVE `TamaguiProvider` so the provider can read `pref` and pass it
 * as Tamagui's `defaultTheme`. Renders its children immediately with the
 * 'light' default; if a persisted 'dark' preference is found it updates once
 * storage resolves (a brief first-paint in light is acceptable and matches the
 * app's existing light-locked default).
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>('light');

  // Hydrate from persisted storage once on mount.
  useEffect(() => {
    let active = true;
    getThemePref()
      .then((stored) => {
        if (active && stored === 'dark') setPrefState('dark');
      })
      .catch(() => {
        /* Absent / unreadable — keep the 'light' default. */
      });
    return () => {
      active = false;
    };
  }, []);

  // Update state immediately (so the UI flips at once) and persist in the
  // background. A failed write only loses the preference across restarts.
  const setPref = useCallback((next: ThemePref) => {
    setPrefState(next);
    setThemePref(next).catch(() => {
      /* Persist is best-effort; the in-memory value already took effect. */
    });
  }, []);

  return createElement(ThemeContext.Provider, { value: { pref, setPref } }, children);
}

/**
 * Read the theme preference + setter.
 *
 * Raises:
 *   Error if called outside a `ThemeProvider`.
 */
export function useThemePref(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useThemePref must be used within a ThemeProvider');
  return ctx;
}
