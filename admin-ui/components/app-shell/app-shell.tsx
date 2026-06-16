/**
 * AppShell — composes the sidebar + topbar + main content area.
 *
 * Server component. Receives the resolved tenants list, active tenant, and
 * the operator's user metadata from the authenticated route layout. The
 * client-side CommandPalette is mounted at the same level so ⌘K works on
 * every page.
 */
import { CommandPalette } from "@/components/command-palette/command-palette";
import { Sidebar } from "@/components/app-shell/sidebar";
import { Topbar, type TopbarTenant, type TopbarUser } from "@/components/app-shell/topbar";

export interface AppShellProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
  user: TopbarUser;
  /** Optional badge counts displayed in the sidebar (e.g. PENDING > 0). */
  pendingReconciliationCount?: number;
  children: React.ReactNode;
}

export function AppShell({
  tenants,
  activeTenantId,
  user,
  pendingReconciliationCount,
  children,
}: AppShellProps) {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[--color-surface-0]">
      <Sidebar pendingCount={pendingReconciliationCount} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar tenants={tenants} activeTenantId={activeTenantId} user={user} />
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <CommandPalette tenants={tenants} activeTenantId={activeTenantId} />
    </div>
  );
}
