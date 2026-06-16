/**
 * Layout for every authenticated route.
 *
 * Server component. Pulls the session + tenants list once at the layout
 * level so every nested page can read the active tenant from the cookie
 * without re-fetching. The AppShell receives the data + renders children.
 */
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell/app-shell";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listTenants } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  let tenants: Awaited<ReturnType<typeof listTenants>> = [];
  try {
    tenants = await listTenants();
  } catch (err) {
    // Backend down or admin lacks tenant-list access — render the shell
    // with an empty tenant list so the operator can still see an error
    // banner on the page instead of a hard crash.
    if (!(err instanceof ApiError)) throw err;
  }

  const activeTenantId =
    (await getActiveTenantId()) ?? tenants[0]?.id ?? null;

  return (
    <AppShell
      tenants={tenants.map((t) => ({
        id: t.id,
        name: t.name,
        baseCurrency: t.base_currency ?? "—",
      }))}
      activeTenantId={activeTenantId}
      user={{
        username: session.user.username ?? session.user.email ?? session.user.id,
        email: session.user.email ?? undefined,
        roles: session.user.roles ?? [],
      }}
    >
      {children}
    </AppShell>
  );
}
