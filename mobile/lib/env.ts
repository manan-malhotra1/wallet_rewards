/**
 * Resolves runtime config (backend URL etc.) from Expo's app.config + env.
 *
 * Order of precedence:
 *   1. process.env.EXPO_PUBLIC_BACKEND_URL (set in .env.development)
 *   2. expo.extra.backendUrl from app.json
 *   3. Hard fallback to http://localhost:8000 so a forgotten env file
 *      doesn't break the demo on the simulator network host.
 */
import Constants from 'expo-constants';

interface Env {
  backendUrl: string;
}

function resolveBackendUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_BACKEND_URL;
  if (fromEnv && fromEnv.length > 0) return fromEnv;
  const fromExtra = Constants.expoConfig?.extra?.backendUrl;
  if (typeof fromExtra === 'string' && fromExtra.length > 0) return fromExtra;
  return 'http://localhost:8000';
}

export const env: Env = {
  backendUrl: resolveBackendUrl(),
};
