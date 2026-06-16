/**
 * Server actions shared across the authenticated app (sign out, tenant
 * switch). These run on the server only; client components import them as
 * plain async functions thanks to the `"use server"` directive.
 */
"use server";

import { cookies } from "next/headers";

import { signOut as nextSignOut } from "@/auth";

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

/**
 * Sign out — delegates to next-auth's signOut (which clears the session
 * cookie + redirects). Wrapped here so client components can bind it to a
 * <form action={...}>.
 */
export async function signOutAction(): Promise<void> {
  await nextSignOut({ redirectTo: "/login" });
}
