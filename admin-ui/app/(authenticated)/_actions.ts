/**
 * Server actions shared across the authenticated app (currently just
 * tenant switch). These run on the server only; client components import
 * them as plain async functions thanks to the `"use server"` directive.
 *
 * Note: signout is intentionally handled client-side via
 * `next-auth/react`'s `signOut` (see `components/app-shell/user-menu.tsx`)
 * because the previous server-action form lived inside a Radix dropdown
 * portal and lost its NEXT_REDIRECT response when the menu closed.
 */
"use server";

import { cookies } from "next/headers";

const TENANT_COOKIE = "sasai_active_tenant";
// 30-day TTL — operators don't switch tenants every session.
const TENANT_TTL = 60 * 60 * 24 * 30;

/**
 * Set the active tenant cookie. Subsequent server-component renders read
 * this via `getActiveTenantId()` (lib/active-tenant.ts).
 */
export async function setActiveTenantAction(tenantId: string): Promise<void> {
  const store = await cookies();
  store.set({
    name: TENANT_COOKIE,
    value: tenantId,
    path: "/",
    httpOnly: true,
    sameSite: "lax",
    maxAge: TENANT_TTL,
  });
}
