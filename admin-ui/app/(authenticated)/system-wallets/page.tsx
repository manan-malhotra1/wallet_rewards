/**
 * /system-wallets — treasury page. Cards per system account with balance,
 * plus a header "Fund user" CTA and per-row Adjust + Transactions actions.
 */
import { Banknote, Landmark, Minus, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenant } from "@/lib/active-tenant";
import { listSystemWallets } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { FundUserDialog } from "./_components/fund-user-dialog";
import { NewBankMirrorDialog } from "./_components/new-bank-mirror-dialog";
import { SystemWalletsView } from "./_components/system-wallets-view";
import { WithdrawFromUserDialog } from "./_components/withdraw-from-user-dialog";

export const dynamic = "force-dynamic";

export default async function SystemWalletsPage() {
  const activeTenant = await getActiveTenant();
  if (!activeTenant) {
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

  const activeTenantId = activeTenant.id;
  let wallets: Awaited<ReturnType<typeof listSystemWallets>> = [];
  let error: ApiError | null = null;
  try {
    wallets = await listSystemWallets(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // Bank mirrors are the eligible counter-legs for withdraw/adjust; the
  // "New bank mirror" dialog offers the currencies already in play.
  const mirrors = wallets.filter((w) => w.account_type === "operator_adjustment");
  const currencies = Array.from(new Set(wallets.map((w) => w.currency))).sort();
  // Default currency for the fund/withdraw/bank-mirror dialogs: the tenant's
  // own base currency, else a currency already in play, else ZAR as a last
  // resort. Never hardcode ZAR as the primary default.
  const defaultCurrency = activeTenant.base_currency ?? currencies[0] ?? "ZAR";

  return (
    <div>
      <PageHeader
        title="System wallets"
        subtitle="Platform-owned ledger accounts."
        actions={
          <div className="flex gap-2">
            <NewBankMirrorDialog
              tenantId={activeTenantId}
              currencies={currencies}
              defaultCurrency={defaultCurrency}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md border border-[--color-border] bg-[--color-surface-1] px-3 text-sm font-medium text-[--color-text-1] hover:bg-[--color-surface-2]"
                >
                  <Landmark className="h-3.5 w-3.5" />
                  New bank mirror
                </button>
              }
            />
            <WithdrawFromUserDialog
              tenantId={activeTenantId}
              defaultCurrency={defaultCurrency}
              mirrors={mirrors}
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
              defaultCurrency={defaultCurrency}
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
            description="System accounts are created when the tenant is provisioned. If this tenant predates that, re-save it on the Tenants page to provision them."
          />
        ) : (
          <SystemWalletsView wallets={wallets} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
