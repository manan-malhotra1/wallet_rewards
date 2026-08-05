/**
 * Reward Budgets page — caps how much can be issued per (scope, window).
 * Phase G.1 / WAL-50.
 */
import { PiggyBank, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { listBudgets, listInstruments } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { Instrument } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { BudgetsTable } from "./_components/budgets-table";
import { CreateBudgetDialog } from "./_components/create-budget-dialog";

export const dynamic = "force-dynamic";

export default async function BudgetsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={PiggyBank}
          title="No active tenant"
          description="Switch to a tenant to manage its reward budgets."
        />
      </div>
    );
  }

  let entries: Awaited<ReturnType<typeof listBudgets>> = [];
  let instruments: Instrument[] = [];
  let error: ApiError | null = null;
  try {
    [entries, instruments] = await Promise.all([
      listBudgets(activeTenantId),
      listInstruments(activeTenantId, "active"),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // Every instrument code is a valid budget currency (PTS + each financial
  // currency). Fall back to PTS so the dialog always has one option.
  const currencies = instruments.map((i) => i.code);
  if (currencies.length === 0) currencies.push("PTS");

  return (
    <div>
      <PageHeader
        title="Reward budgets"
        subtitle="Cap how much can be issued per scope + window. Pre-issuance check protects against runaway rules."
        actions={
          <CreateBudgetDialog
            tenantId={activeTenantId}
            currencies={currencies}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New budget
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load budgets"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && entries.length === 0 ? (
          <EmptyState
            icon={PiggyBank}
            title="No budgets configured"
            description="Without a budget the issuance pipeline has no upper bound. A misconfigured rule could mint unlimited points until someone notices in the audit log."
          />
        ) : (
          <BudgetsTable entries={entries} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
