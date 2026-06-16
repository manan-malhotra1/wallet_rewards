/**
 * Events page — register and observe external event sources.
 *
 * Listing sources requires a backend endpoint that doesn't exist yet
 * (Phase G); for now the page just exposes the register-source dialog and
 * an explanatory empty state.
 */
import { Plus, Receipt } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

import { RegisterEventSourceDialog } from "./_components/register-event-source-dialog";

export const dynamic = "force-dynamic";

export default async function EventsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={Receipt}
          title="No active tenant"
          description="Switch to a tenant to manage its event sources."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Events"
        subtitle="Every external system that publishes reward-triggering events must be registered here."
        actions={
          <RegisterEventSourceDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-8 items-center gap-2 rounded-md bg-[--color-brand] px-3 text-[13px] font-medium text-white hover:opacity-90"
              >
                <Plus className="h-3.5 w-3.5" />
                Register source
              </button>
            }
          />
        }
      />
      <div className="px-6 py-6">
        <EmptyState
          icon={Receipt}
          title="Source list view ships in Phase G"
          description="Right now the backend exposes POST /events/sources but not a list endpoint. Register a source with the button above; the audit log records each registration."
        />
      </div>
    </div>
  );
}
