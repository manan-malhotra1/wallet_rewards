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
  /** Active tenant's logo URL, or null to fall back to the Sasai mark. */
  brandIconUrl?: string | null;
  pendingReconciliationCount?: number;
  approvalsPendingCount?: number;
  children: React.ReactNode;
}

export function AppShell({
  tenants,
  activeTenantId,
  user,
  brandIconUrl,
  pendingReconciliationCount,
  approvalsPendingCount,
  children,
}: AppShellProps) {
  return (
    // bg-transparent (not bg-background) so the body atmosphere shows through.
    <div className="flex h-screen w-screen overflow-hidden bg-transparent text-foreground">
      <Sidebar
        pendingCount={pendingReconciliationCount}
        approvalsPendingCount={approvalsPendingCount}
        brandIconUrl={brandIconUrl}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar tenants={tenants} activeTenantId={activeTenantId} user={user} />
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
      <CommandPalette tenants={tenants} activeTenantId={activeTenantId} />
    </div>
  );
}
