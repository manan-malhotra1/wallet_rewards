/**
 * Active tenant resolution — single source of truth for "which tenant is
 * the operator viewing right now". Reads the cookie set by
 * `setActiveTenantAction`. Falls back to the first tenant the user has
 * access to when no cookie is present (first login).
 */
import { cookies } from "next/headers";

const TENANT_COOKIE = "sasai_active_tenant";

/**
 * Get the active tenant ID from the cookie. Returns null when no cookie
 * is set — callers should default to the first tenant in the list.
 */
export async function getActiveTenantId(): Promise<string | null> {
  const store = await cookies();
  return store.get(TENANT_COOKIE)?.value ?? null;
}
