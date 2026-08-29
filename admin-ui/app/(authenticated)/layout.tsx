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
import { TenantThemeStyle } from "@/components/branding/tenant-theme-style";
import { TooltipProvider } from "@/components/ui/tooltip";
import { getAccessibleTenants, getActiveTenantId } from "@/lib/active-tenant";
import { tenantHasRewards } from "@/lib/tenant-mode";
import {
  getConfigRequestCounts,
  getMoneyOperationCounts,
  getUserOperationCounts,
} from "@/lib/api-endpoints";
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

  let tenants: Awaited<ReturnType<typeof getAccessibleTenants>> = [];
  try {
    tenants = await getAccessibleTenants();
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

  // Resolve the active tenant's branding from the already-fetched list so the
  // runtime theme + sidebar mark render without an extra round trip.
  const activeTenant = tenants.find((t) => t.id === activeTenantId) ?? null;

  // Sidebar "Approvals" badge: total PENDING requests awaiting review across
  // the queues this admin can see. A platform-admin sees every queue; everyone
  // else sees only queues matching an approver role they hold — so the badge
  // never advertises work the admin can't act on. Uses the B7.1 /counts
  // endpoints (one grouped query each) — this layout renders on EVERY page, so
  // it must never fetch queue rows. Best effort: a backend hiccup on any queue
  // just drops that queue's contribution, never the shell.
  const roles = session.user.roles ?? [];
  const isPlatformAdmin = roles.includes("platform-admin");
  const canSee = (role: string) => isPlatformAdmin || roles.includes(role);
  let approvalsPendingCount = 0;
  if (activeTenantId) {
    const queues = [
      { role: "config-approver", counts: getConfigRequestCounts },
      // Epic 18: PENDING treasury money operations awaiting approval.
      { role: "treasury-approver", counts: getMoneyOperationCounts },
      // Epic 3: PENDING user create/edit operations awaiting approval.
      { role: "user-approver", counts: getUserOperationCounts },
    ];
    for (const queue of queues) {
      if (!canSee(queue.role)) continue;
      try {
        const counts = await queue.counts(activeTenantId);
        approvalsPendingCount += counts.by_status["PENDING"] ?? 0;
      } catch (err) {
        if (!(err instanceof ApiError)) throw err;
      }
    }
  }

  return (
    <TooltipProvider delayDuration={200}>
      {/* Per-tenant palette override — no flash: emitted server-side ahead of
          the shell. Renders nothing when the active tenant has no colours. */}
      <TenantThemeStyle
        accent={activeTenant?.brand_accent_color ?? null}
        light={activeTenant?.brand_light_color ?? null}
        glassTransparency={activeTenant?.brand_glass_transparency ?? null}
      />
      <AppShell
        tenants={tenants.map((t) => ({
          id: t.id,
          name: t.name,
          baseCurrency: t.base_currency ?? "—",
        }))}
        activeTenantId={activeTenantId}
        brandIconUrl={activeTenant?.brand_icon_url ?? null}
        // Fail open to the full nav when no tenant resolved — hiding sections
        // on a loading hiccup would look like data loss.
        showRewards={activeTenant ? tenantHasRewards(activeTenant.business_type) : true}
        approvalsPendingCount={approvalsPendingCount}
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
