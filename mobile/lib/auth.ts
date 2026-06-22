/**
 * Session hook + sign-out helper.
 *
 * `useSession()` reads the cached session_token on mount and exposes
 * `{ loading, signedIn }`. The root layout uses it to redirect at app
 * launch (no backend validation — we trust the cached token until a
 * request returns 401, at which point we'll clear it).
 */
import { useEffect, useState } from 'react';

import { logout as apiLogout } from '@/lib/api/auth';
import { clearAll, getSessionToken } from '@/lib/storage';

interface SessionState {
  loading: boolean;
  signedIn: boolean;
}

/** Hook returning whether a session token is cached. Drives launch redirect. */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({
    loading: true,
    signedIn: false,
  });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await getSessionToken();
      if (cancelled) return;
      setState({ loading: false, signedIn: token !== null });
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

/**
 * Sign the user out: invalidate the bearer server-side (best-effort) and
 * clear all locally-cached tokens / phone. Caller navigates to /auth/phone.
 */
export async function signOut(): Promise<void> {
  await apiLogout();
  await clearAll();
}
