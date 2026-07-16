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
import { ServiceUnavailable } from "@/components/branding/service-unavailable";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listConfigRequests, listTenants } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";
import { isBackendUnreachable } from "@/lib/is-backend-unreachable";

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
    // Backend fully unreachable (process down, DNS, refused connection) —
    // render the branded maintenance panel and stop here. Returning instead
    // of throwing means children never render (no cascade of page-level
    // fetch throws) AND the Next.js dev error overlay never appears.
    if (isBackendUnreachable(err)) {
      return <ServiceUnavailable variant="maintenance" />;
    }
    // Backend up but returned an HTTP error (e.g. admin lacks tenant-list
    // access) — degrade to an empty tenant list so the shell still renders
    // with an in-page error banner rather than a hard crash.
    if (!(err instanceof ApiError)) throw err;
  }

  const activeTenantId =
    (await getActiveTenantId()) ?? tenants[0]?.id ?? null;

  // Sidebar badge: number of config change requests awaiting review. Best
  // effort — a backend hiccup just drops the badge, never the shell.
  let configPendingCount = 0;
  if (activeTenantId) {
    try {
      const pending = await listConfigRequests(activeTenantId, "PENDING");
      configPendingCount = pending.length;
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
    }
  }

  return (
    <TooltipProvider delayDuration={200}>
      <AppShell
        tenants={tenants.map((t) => ({
          id: t.id,
          name: t.name,
          baseCurrency: t.base_currency ?? "—",
        }))}
        activeTenantId={activeTenantId}
        configPendingCount={configPendingCount}
        user={{
          username: session.user.username ?? session.user.email ?? session.user.id,
          email: session.user.email ?? undefined,
          roles: session.user.roles ?? [],
        }}
      >
        {children}
      </AppShell>
    </TooltipProvider>
  );
}
