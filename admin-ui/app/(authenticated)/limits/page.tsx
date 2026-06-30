/**
 * Limits page — two scopes:
 *   1. Service-wise (per txn-type/account/currency): min/max + rolling
 *      daily/weekly/monthly count + value caps (Phase G.2 / WAL-51, WAL-234).
 *   2. Wallet-level (per currency): max balance + cumulative send/receive
 *      caps across daily/weekly/monthly (WAL-236).
 */
import { ListChecks, Plus, Wallet } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  listInstruments,
  listLimitConfigs,
  listServices,
  listWalletLimitConfigs,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { Instrument, Service } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateLimitDialog } from "./_components/create-limit-dialog";
import { CreateWalletLimitDialog } from "./_components/create-wallet-limit-dialog";
import { LimitsTable } from "./_components/limits-table";
import { WalletLimitsTable } from "./_components/wallet-limits-table";

export const dynamic = "force-dynamic";

const NEW_BUTTON_CLASS =
  "inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90";

export default async function LimitsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={ListChecks}
          title="No active tenant"
          description="Switch to a tenant to manage its limits."
        />
      </div>
    );
  }

  let configs: Awaited<ReturnType<typeof listLimitConfigs>> = [];
  let walletConfigs: Awaited<ReturnType<typeof listWalletLimitConfigs>> = [];
  let services: Service[] = [];
  let instruments: Instrument[] = [];
  let error: ApiError | null = null;
  try {
    [configs, walletConfigs, services, instruments] = await Promise.all([
      listLimitConfigs(activeTenantId),
      listWalletLimitConfigs(activeTenantId),
      listServices(activeTenantId, "active"),
      listInstruments(activeTenantId, "active"),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // Wallet limits apply to financial wallets only — offer financial currencies.
  const financialInstruments = instruments.filter(
    (i) => i.account_type === "financial_wallet",
  );

  return (
    <div>
      <PageHeader
        title="Limits"
        subtitle="Per-service min/max + rolling daily/weekly/monthly caps, and per-wallet max balance + cumulative send/receive caps. Step 2 of payment orchestration."
        actions={
          <CreateLimitDialog
            tenantId={activeTenantId}
            services={services}
            instruments={instruments}
            trigger={
              <button type="button" className={NEW_BUTTON_CLASS}>
                <Plus className="h-3.5 w-3.5" />
                New limit
              </button>
            }
          />
        }
      />
      <div className="space-y-8 p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load limits"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}

        {/* Service-wise limits */}
        <section>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
            Service limits
          </h2>
          {!error && configs.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title="No service limits configured"
              description="Without a config the orchestration silently allows any amount. Create the first one to bound user activity."
            />
          ) : (
            <LimitsTable configs={configs} tenantId={activeTenantId} />
          )}
        </section>

        {/* Wallet-level limits */}
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">
              Wallet limits
            </h2>
            <CreateWalletLimitDialog
              tenantId={activeTenantId}
              instruments={financialInstruments}
              trigger={
                <button type="button" className={NEW_BUTTON_CLASS}>
                  <Plus className="h-3.5 w-3.5" />
                  New wallet limit
                </button>
              }
            />
          </div>
          {!error && walletConfigs.length === 0 ? (
            <EmptyState
              icon={Wallet}
              title="No wallet limits configured"
              description="Cap a user's max balance and cumulative send/receive volume per currency."
            />
          ) : (
            <WalletLimitsTable configs={walletConfigs} tenantId={activeTenantId} />
          )}
        </section>
      </div>
    </div>
  );
}
