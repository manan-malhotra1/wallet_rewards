/**
 * One-shot fetch of tenant_id (and seeded user map) via /events/sim-bootstrap.
 *
 * Phase F.x (mobile bootstrap): production will replace this with a tenant
 * resolved from the request domain / static env config. For the local demo
 * we follow the same pattern as the mobile-simulator — fetch once, cache
 * in memory for the process lifetime.
 *
 * Backend contract: `{ tenant_id, tenant_name, users: { [phone]: user_id } }`.
 * Available only when SIMULATOR_DEV_MODE=true on the backend (it always is
 * in our local stack).
 */
import { env } from '@/lib/env';

export interface Bootstrap {
  tenant_id: string;
  tenant_name: string;
  users: Record<string, string>;
}

let cached: Bootstrap | null = null;
let pending: Promise<Bootstrap> | null = null;

/**
 * Return the cached bootstrap payload, fetching on first call.
 *
 * Concurrent callers share the same in-flight Promise so we never hit the
 * backend twice on app launch (auth/phone fires it; the redirect from /
 * might also fire it).
 */
export async function getBootstrap(): Promise<Bootstrap> {
  if (cached) return cached;
  if (pending) return pending;
  pending = (async () => {
    const res = await fetch(`${env.backendUrl}/api/v1/events/sim-bootstrap`);
    if (!res.ok) {
      pending = null;
      throw new Error(
        `Sim bootstrap failed (${res.status}). Is the backend running ` +
          'with SIMULATOR_DEV_MODE=true and has `make seed` been run?',
      );
    }
    const data = (await res.json()) as Bootstrap;
    cached = data;
    pending = null;
    return data;
  })();
  return pending;
}

/** Convenience accessor — returns just the tenant_id. */
export async function getTenantId(): Promise<string> {
  const b = await getBootstrap();
  return b.tenant_id;
}
