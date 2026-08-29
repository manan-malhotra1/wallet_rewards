/**
 * Active tenant resolution — single source of truth for "which tenant is
 * the operator viewing right now". Reads the cookie set by
 * `setActiveTenantAction`. Falls back to the first tenant the user has
 * access to when no cookie is present (first login).
 */
import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";

import { ApiError } from "@/lib/api";
import { listTenants } from "@/lib/api-endpoints";
import type { Tenant } from "@/lib/api-types";

const TENANT_COOKIE = "sasai_active_tenant";

/**
 * The tenants this operator can access, memoised for the current request.
 *
 * The API client sets `cache: "no-store"`, so Next's own fetch deduplication
 * does not apply — without this memo each resolver call below would be its own
 * round trip, and the authenticated layout would fetch the list a second time.
 *
 * Errors propagate deliberately: the layout distinguishes "backend
 * unreachable" from "operator lacks tenant access", so it must see the throw.
 */
export const getAccessibleTenants = cache(listTenants);

/**
 * Resolve the active tenant ID for the current operator.
 *
 * Thin projection of {@link getActiveTenant} so the id used to scope queries
 * can never diverge from the tenant the shell displays — see that function
 * for the cookie-validation rule.
 *
 * Returns:
 *   The active tenant UUID, or null only when the operator has no tenants
 *   (or the backend is unreachable).
 */
export async function getActiveTenantId(): Promise<string | null> {
  return (await getActiveTenant())?.id ?? null;
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
export const getActiveTenant = cache(async (): Promise<Tenant | null> => {
  const store = await cookies();
  const fromCookie = store.get(TENANT_COOKIE)?.value;

  // Swallow API errors so a backend hiccup degrades to "no tenant" rather
  // than crashing every authenticated page. This is the single resolution
  // point: getActiveTenantId() projects the id off whatever we return.
  try {
    const tenants = await getAccessibleTenants();
    // Validate the cookie against the tenants this operator can actually
    // reach. The cookie carries a 30-day TTL on a fixed origin, so one left
    // by an earlier deployment (a re-seeded local DB mints new tenant ids)
    // would otherwise scope every query to a tenant that does not exist here
    // — rendering empty "not found" pages under a valid-looking tenant name.
    if (fromCookie) {
      return tenants.find((t) => t.id === fromCookie) ?? tenants[0] ?? null;
    }
    return tenants[0] ?? null;
  } catch (err) {
    if (err instanceof ApiError) return null;
    throw err;
  }
});
