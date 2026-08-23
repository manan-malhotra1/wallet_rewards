/**
 * User types page (spec §9) — the tenant's catalog of customer kinds, grouped
 * under the three fixed categories.
 *
 * Types are runtime data, not code: an operator adds their own alongside the
 * seeded system ones, and every downstream config (pricing, limits, commission,
 * tax) can then be scoped to them. Retail and Business carry a two-level
 * hierarchy; Consumers is flat.
 *
 * There is no direct write endpoint. Create / edit / retire all PROPOSE a
 * change through the config maker-checker pipeline (config_type "user_type"),
 * which a second admin approves in the Configuration approvals tab.
 */
import { Plus, Users2 } from "lucide-react";

import { auth } from "@/auth";
import { ApiError } from "@/lib/api";
import { getUserTypeCatalog } from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { UserTypeCatalog } from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateUserTypeDialog } from "./_components/create-user-type-dialog";
import { UserTypesBoard } from "./_components/user-types-board";

export const dynamic = "force-dynamic";

export default async function UserTypesPage() {
  const session = await auth();
  // Only platform-admins may propose config changes; the backend also 403s,
  // this just hides affordances that would fail for other admins.
  const canPropose = session?.user?.roles?.includes("platform-admin") ?? false;

  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Users2}
          title="No active tenant"
          description="Switch to a tenant to manage its user types."
        />
      </div>
    );
  }

  let catalog: UserTypeCatalog | null = null;
  let error: ApiError | null = null;
  try {
    // Retired types are shown here (and only here) — this is the page where an
    // operator reactivates one, and where a code collision has to be visible.
    catalog = await getUserTypeCatalog(activeTenantId, true);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="User types"
        subtitle="The kinds of customer this tenant serves, grouped under Consumers, Retail and Business. Pricing, limits, commission and tax are all scoped to these. Changes require a second admin's approval."
        actions={
          canPropose && catalog ? (
            <CreateUserTypeDialog
              tenantId={activeTenantId}
              catalog={catalog}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  New user type
                </button>
              }
            />
          ) : undefined
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load user types"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {catalog && (
          <UserTypesBoard
            catalog={catalog}
            tenantId={activeTenantId}
            canPropose={canPropose}
          />
        )}
      </div>
    </div>
  );
}
