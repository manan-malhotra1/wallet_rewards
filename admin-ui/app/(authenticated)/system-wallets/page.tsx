/**
 * /system-wallets — treasury page. Cards per system account with balance,
 * plus a header "Fund user" CTA and per-row Adjust + Transactions actions.
 */
import { Banknote, Minus, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listSystemWallets } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { FundUserDialog } from "./_components/fund-user-dialog";
import { SystemWalletGrid } from "./_components/system-wallet-grid";
import { WithdrawFromUserDialog } from "./_components/withdraw-from-user-dialog";

export const dynamic = "force-dynamic";

export default async function SystemWalletsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Banknote}
          title="No active tenant"
          description="Switch to a tenant to see its treasury."
        />
      </div>
    );
  }

  let wallets: Awaited<ReturnType<typeof listSystemWallets>> = [];
  let error: ApiError | null = null;
  try {
    wallets = await listSystemWallets(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="System wallets"
        subtitle="Platform-owned ledger accounts."
        actions={
          <div className="flex gap-2">
            <WithdrawFromUserDialog
              tenantId={activeTenantId}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-[--color-border] bg-[--color-surface-1] px-3 text-sm font-medium text-[--color-text-1] hover:bg-[--color-surface-2]"
                >
                  <Minus className="h-3.5 w-3.5" />
                  Withdraw
                </button>
              }
            />
            <FundUserDialog
              tenantId={activeTenantId}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Fund user
                </button>
              }
            />
          </div>
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load system wallets"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && wallets.length === 0 ? (
          <EmptyState
            icon={Banknote}
            title="No system accounts yet"
            description="A tenant gets its system_points_issuance + system_cash_inflow on first seed. Run make seed to populate."
          />
        ) : (
          <SystemWalletGrid wallets={wallets} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
