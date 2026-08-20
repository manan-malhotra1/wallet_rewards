/**
 * Points rates page — per-currency points→fiat conversion rates for internal
 * redemption (Module 11b, Pay-PRD-1210/1280/1295), including the per-txn
 * anti-drain caps. Writes flow through the config maker-checker pipeline
 * (config_type "conversion_rate"): create / edit / delete PROPOSE a change
 * that a second admin approves in the Configuration approvals tab. Without a
 * rate, internal redemption into that currency is blocked (fail-closed).
 */
import { Repeat, Plus } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import {
  listConfigRequests,
  listConversionRates,
  listInstruments,
} from "@/lib/api-endpoints";
import { getActiveTenant } from "@/lib/active-tenant";
import type {
  ConfigChangeRequest,
  Instrument,
  PointsConversionRate,
} from "@/lib/api-types";
import { changeProposedScopeKeys } from "@/lib/config-scope";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateRateDialog } from "./_components/create-rate-dialog";
import { RatesChangesRequested } from "./_components/rates-changes-requested";
import { RatesTable } from "./_components/rates-table";

export const dynamic = "force-dynamic";

export default async function RedemptionRatesPage() {
  const session = await auth();
  // Only platform-admins may propose config changes; the backend also 403s,
  // this just hides affordances that would fail for other admins.
  const canPropose = session?.user?.roles?.includes("platform-admin") ?? false;
  const currentAdminId = session?.user?.id ?? "";

  const activeTenant = await getActiveTenant();
  if (!activeTenant) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Repeat}
          title="No active tenant"
          description="Switch to a tenant to manage its points conversion rates."
        />
      </div>
    );
  }
  const activeTenantId = activeTenant.id;
  const defaultCurrency = activeTenant.base_currency ?? "ZAR";

  let rates: PointsConversionRate[] = [];
  let openRequests: ConfigChangeRequest[] = [];
  let instruments: Instrument[] = [];
  let error: ApiError | null = null;
  try {
    let requests: ConfigChangeRequest[] = [];
    [rates, requests, instruments] = await Promise.all([
      listConversionRates(activeTenantId),
      listConfigRequests(activeTenantId, undefined, "conversion_rate"),
      listInstruments(activeTenantId, "active"),
    ]);
    openRequests = requests.filter(
      (r) => r.status === "PENDING" || r.status === "CHANGES_REQUESTED",
    );
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // A rate converts points INTO one of the tenant's financial currencies, so
  // the dialog offers exactly those (never a free-text code that no wallet
  // exists for). Points instruments are excluded — PTS is always the source.
  const financialCurrencies = instruments
    .filter((i) => i.account_type === "financial_wallet")
    .map((i) => i.code);

  return (
    <div>
      <PageHeader
        title="Points rates"
        subtitle="How many points convert into wallet money per currency, with per-transaction anti-drain caps. Currencies without a rate cannot be redeemed into (fail-closed). Changes require a second admin's approval."
        actions={
          canPropose ? (
            <CreateRateDialog
              tenantId={activeTenantId}
              defaultCurrency={defaultCurrency}
              currencies={financialCurrencies}
              configuredCurrencies={rates.map((r) => r.currency)}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New rate
                </button>
              }
            />
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load conversion rates"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <RatesChangesRequested
            requests={openRequests}
            tenantId={activeTenantId}
            currentAdminId={currentAdminId}
            currencies={financialCurrencies}
          />
        )}
        {!error && rates.length === 0 ? (
          <EmptyState
            icon={Repeat}
            title="No conversion rates"
            description="Internal redemption is blocked until a rate exists — users cannot convert points into any currency. Propose a rate to enable it."
          />
        ) : (
          !error && (
            <RatesTable
              rates={rates}
              tenantId={activeTenantId}
              canPropose={canPropose}
              currencies={financialCurrencies}
              changeProposedKeys={changeProposedScopeKeys(
                "conversion_rate",
                openRequests,
                rates,
              )}
            />
          )
        )}
      </div>
    </div>
  );
}
