/**
 * Rules page — list every rule in the active tenant; create new rules via
 * a dialog wizard.
 *
 * The wizard supports all 7 rule types from PRD §6.9, with the form
 * mutating to reveal type-specific fields (count_threshold for milestone /
 * streak, min_amount for value_based, etc).
 */
import { GitMerge, Plus } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { listRules } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateRuleDialog } from "./_components/create-rule-dialog";
import { RulesTable } from "./_components/rules-table";

export const dynamic = "force-dynamic";

export default async function RulesPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={GitMerge}
          title="No active tenant"
          description="Switch to a tenant to see its rules."
        />
      </div>
    );
  }

  let rules: Awaited<ReturnType<typeof listRules>> = [];
  let error: ApiError | null = null;
  try {
    rules = await listRules(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Rules"
        subtitle="Rules govern when a user earns rewards. Active rules fire on every matching event."
        actions={
          <CreateRuleDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-8 items-center gap-2 rounded-md bg-[--color-brand] px-3 text-[13px] font-medium text-white hover:opacity-90"
              >
                <Plus className="h-3.5 w-3.5" />
                New rule
              </button>
            }
          />
        }
      />
      <div className="px-6 py-6">
        {error && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load rules"
            description={error.message}
          />
        )}
        {!error && rules.length === 0 ? (
          <EmptyState
            icon={GitMerge}
            title="No rules yet"
            description="Rules trigger rewards when users meet configured conditions. Create the first one to start earning points or cashback."
          />
        ) : (
          <RulesTable rules={rules} />
        )}
      </div>
    </div>
  );
}
