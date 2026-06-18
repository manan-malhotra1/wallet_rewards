/**
 * Segments page — list every cohort in the active tenant and create new ones.
 *
 * Static cohorts only in this phase: an admin assigns each user explicitly.
 * Dynamic "users who did X" segments are deferred to Phase 2.
 */
import { Layers, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listSegments } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateSegmentDialog } from "./_components/create-segment-dialog";
import { SegmentsTable } from "./_components/segments-table";

export const dynamic = "force-dynamic";

export default async function SegmentsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={Layers}
          title="No active tenant"
          description="Switch to a tenant to manage its segments."
        />
      </div>
    );
  }

  let segments: Awaited<ReturnType<typeof listSegments>> = [];
  let error: ApiError | null = null;
  try {
    segments = await listSegments(activeTenantId);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Segments"
        subtitle="User cohorts. Bind a campaign or a multiplier to a segment to target a specific group of users."
        actions={
          <CreateSegmentDialog
            tenantId={activeTenantId}
            trigger={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3.5 w-3.5" />
                New segment
              </button>
            }
          />
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load segments"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && segments.length === 0 ? (
          <EmptyState
            icon={Layers}
            title="No segments yet"
            description="Create a segment to start grouping users. After that, assign users to it via the API or the user detail page."
          />
        ) : (
          <SegmentsTable segments={segments} />
        )}
      </div>
    </div>
  );
}
