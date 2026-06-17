/**
 * Step-up PIN policies page — configurable thresholds above which a
 * user must re-enter their PIN. Per-(tenant, transaction_type, currency).
 */
import { ShieldAlert, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { listStepUpPolicies } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateStepUpDialog } from "./_components/create-step-up-dialog";
import { StepUpTable } from "./_components/step-up-table";

export const dynamic = "force-dynamic";

export default async function StepUpPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={ShieldAlert}
          title="No active tenant"
          description="Switch to a tenant to manage its step-up PIN policies."
        />
      </div>
    );
  }

  let policies: Awaited<ReturnType<typeof listStepUpPolicies>> = [];
  let error: ApiError | null = null;
  try {
    policies = await listStepUpPolicies(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Step-up PIN"
        subtitle="Transactions above the configured threshold require the user to re-enter their PIN. Below threshold the session token is enough."
        actions={
          <CreateStepUpDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New policy
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load policies"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && policies.length === 0 ? (
          <EmptyState
            icon={ShieldAlert}
            title="No step-up policies"
            description="Without policies, every transaction goes through with just the session token. Add one to require PIN re-entry above a chosen amount."
          />
        ) : (
          <StepUpTable policies={policies} tenantId={activeTenantId} />
        )}
      </div>
    </div>
  );
}
