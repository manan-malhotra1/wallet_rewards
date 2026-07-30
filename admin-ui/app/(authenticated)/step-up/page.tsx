/**
 * Step-up PIN policies page — configurable thresholds above which a user must
 * re-enter their PIN. Per-(tenant, transaction_type, currency). Writes flow
 * through the config maker-checker pipeline (config_type "step_up"): create /
 * edit / delete PROPOSE a change that a second admin approves in the
 * Configuration approvals tab.
 */
import { ShieldAlert, Plus } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import { listConfigRequests, listStepUpPolicies } from "@/lib/api-endpoints";
import { getActiveTenant } from "@/lib/active-tenant";
import type { ConfigChangeRequest, StepUpPolicy } from "@/lib/api-types";
import { changeProposedScopeKeys } from "@/lib/config-scope";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateStepUpDialog } from "./_components/create-step-up-dialog";
import { StepUpChangesRequested } from "./_components/step-up-changes-requested";
import { StepUpTable } from "./_components/step-up-table";

export const dynamic = "force-dynamic";

export default async function StepUpPage() {
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
          icon={ShieldAlert}
          title="No active tenant"
          description="Switch to a tenant to manage its step-up PIN policies."
        />
      </div>
    );
  }
  const activeTenantId = activeTenant.id;
  // Fiat step-up policies default to the tenant's own currency, not "ZAR".
  const defaultCurrency = activeTenant.base_currency ?? "ZAR";

  let policies: StepUpPolicy[] = [];
  let openRequests: ConfigChangeRequest[] = [];
  let error: ApiError | null = null;
  try {
    let requests: ConfigChangeRequest[] = [];
    [policies, requests] = await Promise.all([
      listStepUpPolicies(activeTenantId),
      // All in-flight step-up proposals (both open statuses) so anyone can see
      // a change is under approval; card actions are maker-gated.
      listConfigRequests(activeTenantId, undefined, "step_up"),
    ]);
    openRequests = requests.filter(
      (r) => r.status === "PENDING" || r.status === "CHANGES_REQUESTED",
    );
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Step-up PIN"
        subtitle="Transactions above the configured threshold require the user to re-enter their PIN. Proposed changes require a second admin's approval."
        actions={
          canPropose ? (
            <CreateStepUpDialog
              tenantId={activeTenantId}
              defaultCurrency={defaultCurrency}
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
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load policies"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && (
          <StepUpChangesRequested
            requests={openRequests}
            tenantId={activeTenantId}
            currentAdminId={currentAdminId}
          />
        )}
        {!error && policies.length === 0 ? (
          <EmptyState
            icon={ShieldAlert}
            title="No step-up policies"
            description="Without policies, every transaction goes through with just the session token. Propose one to require PIN re-entry above a chosen amount."
          />
        ) : (
          !error && (
            <StepUpTable
              policies={policies}
              tenantId={activeTenantId}
              canPropose={canPropose}
              changeProposedKeys={changeProposedScopeKeys(
                "step_up",
                openRequests,
                policies,
              )}
            />
          )
        )}
      </div>
    </div>
  );
}
