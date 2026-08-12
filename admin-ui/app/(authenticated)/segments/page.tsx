/**
 * Segments page — group-sectioned list of every cohort in the active tenant
 * (Segmentation Phase 1 Task 11): one collapsible section per segment group,
 * each holding a priority-ordered table of its segments, plus group CRUD and
 * a manual recompute trigger for the batch evaluator.
 *
 * Segments are static (admin-assigned) or dynamic (criteria-evaluated by the
 * batch evaluator). Groups now drive the page body itself (one
 * `<GroupSection>` per group), not just the create-segment dialog's picker —
 * so a failed groups fetch is surfaced with its own error banner rather than
 * silently rendering a false "No segment groups yet" empty state.
 */
import { Layers, Plus } from "lucide-react";

import { auth } from "@/auth";
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
  const session = await auth();
  // Only platform-admins may delete a segment group; the backend also 409s a
  // non-platform-admin's attempt, this just hides the affordance up front
  // per frontend-admin.md's "read role from session, conditionally render
  // action affordances" convention (see limits/page.tsx for the same check).
  const canDeleteGroups = session?.user?.roles?.includes("platform-admin") ?? false;

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

  // Metrics/services only feed the create-segment dialog's pickers — a
  // failure fetching either just leaves that picker empty (the dialog
  // already handles an empty `metrics`/`services` list gracefully), so they
  // stay best-effort. Groups are different: they now drive the page body
  // itself (one `<GroupSection>` per group, below), so silently collapsing a
  // rejected groups fetch to `[]` would render a false "No segment groups
  // yet" empty state over a tenant that actually has groups — `groupsError`
  // is captured separately and surfaced as its own banner instead. All
  // three still go through one `Promise.allSettled` (not `Promise.all`) so
  // a metrics/services rejection can't take the groups fetch down with it,
  // and vice versa.
  const [groupsResult, metricsResult, servicesResult] = await Promise.allSettled([
    listSegmentGroups(activeTenantId),
    listSegmentMetrics(),
    listServices(activeTenantId, "active"),
  ]);
  const groups = groupsResult.status === "fulfilled" ? groupsResult.value : [];
  const groupsError =
    groupsResult.status === "rejected" && groupsResult.reason instanceof ApiError
      ? groupsResult.reason
      : null;
  const metrics = metricsResult.status === "fulfilled" ? metricsResult.value : [];
  const services = servicesResult.status === "fulfilled" ? servicesResult.value : [];

  // System groups (seeded defaults, e.g. the default tier lens) surface
  // first — an admin scanning the page expects the platform-provisioned
  // groups before any custom ones — then alphabetical within each tier.
  const sortedGroups = [...groups].sort((a, b) => {
    if (a.is_system !== b.is_system) return a.is_system ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  // A segment whose group_id doesn't match any fetched group — its real
  // group was deleted out from under it, or the groups fetch above only
  // partially/never succeeded — would otherwise vanish from the page: every
  // segment below is rendered via a `group_id` filter keyed off a real
  // group, so an orphan needs its own catch-all section rather than
  // silently under-reporting the tenant's segment count.
  const knownGroupIds = new Set(groups.map((g) => g.id));
  const orphanedSegments = segments.filter((s) => !knownGroupIds.has(s.group_id));

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
        {groupsError && (
          <ErrorBanner
            title="Couldn't load segment groups"
            description={`${groupsError.errorCode}: ${groupsError.message}`}
          />
        )}
        {!error && !groupsError && sortedGroups.length === 0 && (
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
              canDelete={canDeleteGroups}
            />
          ))}
        {!error && orphanedSegments.length > 0 && (
          <GroupSection
            key="unknown-group"
            group={{
              id: "__unknown__",
              tenant_id: activeTenantId,
              name: "Unknown group",
              description:
                "These segments reference a group that no longer resolves — deleted, or missing because the groups fetch above failed.",
              is_system: false,
              created_at: "",
              updated_at: "",
            }}
            segments={orphanedSegments}
            tenantId={activeTenantId}
            canDelete={false}
          />
        )}
      </div>
    </div>
  );
}
