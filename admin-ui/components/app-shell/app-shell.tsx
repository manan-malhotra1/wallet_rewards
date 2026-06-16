/**
 * AppShell — composes sidebar + topbar + main + command palette.
 *
 * Server component. Receives resolved tenants + active tenant + user
 * metadata from the authenticated route layout.
 */
import { CommandPalette } from "@/components/command-palette/command-palette";
import { Sidebar } from "@/components/app-shell/sidebar";
import { Topbar, type TopbarTenant, type TopbarUser } from "@/components/app-shell/topbar";

export interface AppShellProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
  user: TopbarUser;
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
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar pendingCount={pendingReconciliationCount} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar tenants={tenants} activeTenantId={activeTenantId} user={user} />
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <CommandPalette tenants={tenants} activeTenantId={activeTenantId} />
    </div>
  );
}
