/**
 * Segments page — group-sectioned list of every cohort in the active tenant
 * (Segmentation Phase 1 Task 11): one collapsible section per segment group,
 * each holding a priority-ordered table of its segments, plus group CRUD and
 * a manual recompute trigger for the batch evaluator.
 *
 * Segments are static (admin-assigned) or dynamic (criteria-evaluated by the
 * batch evaluator); the create-segment dialog fetches the group/metric/
 * service vocabulary a dynamic segment needs.
 */
import { Layers, Plus } from "lucide-react";

import { ApiError } from "@/lib/api";
import { getActiveTenantId } from "@/lib/active-tenant";
import { listSegmentGroups, listSegmentMetrics, listSegments, listServices } from "@/lib/api-endpoints";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CreateGroupDialog } from "./_components/create-group-dialog";
import { CreateSegmentDialog } from "./_components/create-segment-dialog";
import { GroupSection } from "./_components/group-section";
import { RecomputeButton } from "./_components/recompute-button";

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

  // Groups/metrics/services only feed the create dialog's pickers — they're
  // never why an admin loads this page. A failure fetching any one of them
  // must not blank the segments list above (which may have already loaded
  // fine), so they're fetched independently of `segments` AND of each other
  // via `Promise.allSettled` rather than a `Promise.all` that would abort
  // all three the moment the first one rejects. A rejected auxiliary fetch
  // just leaves that picker empty (the dialog already handles an empty
  // `groups`/`metrics`/`services` list gracefully).
  const [groupsResult, metricsResult, servicesResult] = await Promise.allSettled([
    listSegmentGroups(activeTenantId),
    listSegmentMetrics(),
    listServices(activeTenantId, "active"),
  ]);
  const groups = groupsResult.status === "fulfilled" ? groupsResult.value : [];
  const metrics = metricsResult.status === "fulfilled" ? metricsResult.value : [];
  const services = servicesResult.status === "fulfilled" ? servicesResult.value : [];

  // System groups (seeded defaults, e.g. the default tier lens) surface
  // first — an admin scanning the page expects the platform-provisioned
  // groups before any custom ones — then alphabetical within each tier.
  const sortedGroups = [...groups].sort((a, b) => {
    if (a.is_system !== b.is_system) return a.is_system ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div>
      <PageHeader
        title="Segments"
        subtitle="User cohorts, grouped into exclusive tiers. Within a group, the highest-priority matching segment wins."
        actions={
          <div className="flex items-center gap-2">
            <RecomputeButton tenantId={activeTenantId} />
            <CreateGroupDialog
              tenantId={activeTenantId}
              trigger={
                <button
                  type="button"
                  className="inline-flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm font-medium hover:bg-accent"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New group
                </button>
              }
            />
            <CreateSegmentDialog
              tenantId={activeTenantId}
              groups={groups}
              metrics={metrics}
              services={services}
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
          </div>
        }
      />
      <div className="p-6">
        {error && (
          <ErrorBanner
            title="Couldn't load segments"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && sortedGroups.length === 0 && (
          <EmptyState
            icon={Layers}
            title="No segment groups yet"
            description="Create a segment group first — the exclusive-tier lens segments live in — then add segments to it."
          />
        )}
        {!error &&
          sortedGroups.map((group) => (
            <GroupSection
              key={group.id}
              group={group}
              segments={segments.filter((s) => s.group_id === group.id)}
              tenantId={activeTenantId}
            />
          ))}
      </div>
    </div>
  );
}
