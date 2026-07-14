/**
 * usePersistedState — useState that survives reloads by mirroring to
 * localStorage. Used by the simulator's forms so a chosen user / event
 * type / amount is remembered between visits.
 */
"use client";

import * as React from "react";

/**
 * Like React.useState, but the value is persisted under `key` in
 * localStorage and rehydrated on mount.
 *
 * The initial render always uses `initial` (so server and client markup
 * match); the stored value is applied in an effect after mount to avoid
 * hydration mismatches.
 *
 * Args:
 *   key: localStorage key. Namespace it to avoid collisions.
 *   initial: default value when nothing is stored yet.
 */
export function usePersistedState<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = React.useState<T>(initial);

  // Rehydrate once on mount — after hydration so SSR/CSR markup matches.
  React.useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored !== null) setValue(JSON.parse(stored) as T);
    } catch {
      // Ignore malformed/blocked storage — fall back to the default.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Persist on every change.
  React.useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Storage full or unavailable — persistence is best-effort.
    }
  }, [key, value]);

  return [value, setValue];
}
