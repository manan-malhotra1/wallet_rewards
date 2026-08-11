/**
 * Bonus multipliers page (Epic 10 / WAL-78) — list every points-boost
 * multiplier in the active tenant, create new ones, delete stale ones.
 *
 * A multiplier amplifies a rule's points value at issuance time; overlapping
 * multipliers never stack — the single highest matching factor wins.
 */
import { Plus, Zap } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listMultipliers, listRules, listSegments } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateMultiplierDialog } from "./_components/create-multiplier-dialog";
import { MultipliersTable } from "./_components/multipliers-table";

export const dynamic = "force-dynamic";

export default async function MultipliersPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Zap}
          title="No active tenant"
          description="Switch to a tenant to manage its bonus multipliers."
        />
      </div>
    );
  }

  let multipliers: Awaited<ReturnType<typeof listMultipliers>> = [];
  let rules: Awaited<ReturnType<typeof listRules>> = [];
  let segments: Awaited<ReturnType<typeof listSegments>> = [];
  let error: ApiError | null = null;
  try {
    // Rules + segments feed the scope pickers and resolve ids to names in
    // the table; fetched together since the page needs all three anyway.
    [multipliers, rules, segments] = await Promise.all([
      listMultipliers(activeTenantId),
      listRules(activeTenantId),
      listSegments(activeTenantId),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Bonus multipliers"
        subtitle="Time-boxed points boosts. The highest matching multiplier applies at issuance — overlaps never stack. Points rules only; cashback pays face value."
        actions={
          <CreateMultiplierDialog
            tenantId={activeTenantId}
            rules={rules}
            segments={segments}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New multiplier
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load multipliers"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && multipliers.length === 0 ? (
          <EmptyState
            icon={Zap}
            title="No multipliers yet"
            description="Create one to boost points issuance for a promo window — tenant-wide, per rule, or per segment."
          />
        ) : (
          <MultipliersTable
            multipliers={multipliers}
            rules={rules}
            segments={segments}
          />
        )}
      </div>
    </div>
  );
}
