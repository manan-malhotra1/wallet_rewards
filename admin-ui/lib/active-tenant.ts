/**
 * Active tenant resolution — single source of truth for "which tenant is
 * the operator viewing right now". Reads the cookie set by
 * `setActiveTenantAction`. Falls back to the first tenant the user has
 * access to when no cookie is present (first login).
 */
import "server-only";

import { cookies } from "next/headers";

import { ApiError } from "@/lib/api";
import { listTenants } from "@/lib/api-endpoints";
import type { Tenant } from "@/lib/api-types";

const TENANT_COOKIE = "sasai_active_tenant";

/**
 * Resolve the active tenant ID for the current operator.
 *
 * Reads the `sasai_active_tenant` cookie first. On first login the cookie
 * is absent, so we fall back to the first tenant the operator can access —
 * mirroring the layout's switcher default so tenant-scoped pages (e.g.
 * system wallets) render real data instead of an empty "no tenant" state.
 *
 * Returns:
 *   The active tenant UUID, or null only when the operator has no tenants
 *   (or the backend is unreachable).
 */
export async function getActiveTenantId(): Promise<string | null> {
  const store = await cookies();
  const fromCookie = store.get(TENANT_COOKIE)?.value;
  if (fromCookie) return fromCookie;

  // No cookie yet (first login): default to the operator's first tenant.
  // Swallow API errors here so a backend hiccup degrades to "no tenant"
  // rather than crashing every authenticated page.
  try {
    const tenants = await listTenants();
    return tenants[0]?.id ?? null;
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}

/**
 * Resolve the full active Tenant for the current operator.
 *
 * Same resolution rule as {@link getActiveTenantId} (cookie first, else the
 * operator's first tenant) but returns the whole record so callers can read
 * per-tenant fields such as `base_currency` — e.g. money/config dialogs that
 * must default the currency to the tenant's own currency, never a hardcoded
 * "ZAR".
 *
 * Returns:
 *   The active Tenant, or null when the operator has no tenants (or the
 *   backend is unreachable).
 */
export async function getActiveTenant(): Promise<Tenant | null> {
  const store = await cookies();
  const fromCookie = store.get(TENANT_COOKIE)?.value;

  // Swallow API errors so a backend hiccup degrades to "no tenant" rather
  // than crashing every authenticated page (mirrors getActiveTenantId).
  try {
    const tenants = await listTenants();
    if (fromCookie) {
      return tenants.find((t) => t.id === fromCookie) ?? tenants[0] ?? null;
    }
    return tenants[0] ?? null;
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
}
