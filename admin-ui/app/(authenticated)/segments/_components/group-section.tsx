/**
 * <GroupSection> — one collapsible segment group with its priority-ordered
 * segment table (Segmentation Phase 1 Task 11).
 *
 * Within a group only the highest-priority matching segment applies to a
 * given user, so segments are always listed priority DESC (ties broken by
 * name) to match that evaluation order. The assign-user affordance carried
 * over from the pre-Task-11 `<SegmentsTable>` only makes sense for static
 * (admin-assigned) segments — dynamic ones have their membership computed
 * by the batch evaluator, never hand-picked — so it's rendered per-row and
 * gated on `segment.criteria == null`.
 *
 * `memberCounts` (Story B1.4+) is optional and degrades gracefully: `null`
 * (the fetch failed, or the caller hasn't loaded it) hides the group
 * header's "N users" annotation and the per-segment Members column
 * entirely, rather than rendering a column of misleading zeroes.
 */
"use client";

import { AlertTriangle, ChevronDown, ChevronRight, Trash2, UserPlus } from "lucide-react";
import * as React from "react";

import {
  addUserToSegmentAction,
  deleteSegmentGroupAction,
} from "@/app/(authenticated)/segments/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type {
  MemberCounts,
  Segment,
  SegmentGroup,
  SegmentMetricInfo,
  Service,
} from "@/lib/api-types";
import { summarizeCriteria } from "@/lib/segment-criteria";
import { formatTimestamp } from "@/lib/utils";

import { EditSegmentDialog } from "./edit-segment-dialog";

/** Sort segments the way the evaluator ranks them: priority DESC, name ASC on ties. */
function byPriorityDesc(a: Segment, b: Segment): number {
  if (b.priority !== a.priority) return b.priority - a.priority;
  return a.name.localeCompare(b.name);
}

/** Render a segment's criteria as one line, or an em-dash for a static segment. */
function criteriaText(segment: Segment): string {
  return segment.criteria != null ? summarizeCriteria(segment.criteria) : "—";
}

/**
 * Render the "Last evaluated" cell. A dynamic segment whose criteria
 * changed since the last recompute has its `last_evaluated_at` nulled by
 * the backend (see the evaluator's write path) — surface that as an
 * actionable "Pending recompute" rather than a bare dash, which would read
 * as "never touched" instead of "stale, needs the evaluator to run".
 */
function lastEvaluatedText(segment: Segment): string {
  if (segment.last_evaluated_at) return formatTimestamp(segment.last_evaluated_at);
  return segment.criteria != null ? "Pending recompute" : "—";
}

export function GroupSection({
  group,
  segments,
  tenantId,
  groups,
  metrics,
  services,
  canDelete = true,
  memberCounts = null,
}: {
  group: SegmentGroup;
  segments: Segment[];
  tenantId: string;
  // Threaded through to <EditSegmentDialog> for its group-move picker and
  // (for a segment gaining criteria for the first time) its criteria
  // builder — page.tsx already fetches all three for the create-segment
  // dialog, so this just reuses that same fetch rather than re-fetching.
  groups: SegmentGroup[];
  metrics: SegmentMetricInfo[];
  services: Service[];
  canDelete?: boolean;
  // `null` = counts unavailable (fetch failed, or not loaded) — every
  // count-derived affordance below is hidden rather than shown as zero.
  memberCounts?: MemberCounts | null;
}) {
  const [open, setOpen] = React.useState(true);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [pending, setPending] = React.useState<string | null>(null);
  // No `tenantId` field here — `onAddUser` below always submits the
  // segment's own `tenant_id` (looked up fresh from `s.tenant_id` at call
  // time), so a copy on this prompt's state would just be dead weight.
  const [userIdPrompt, setUserIdPrompt] = React.useState<{
    segmentId: string;
    value: string;
  } | null>(null);
  const { toast } = useToast();
  const bodyId = React.useId();

  const sorted = [...segments].sort(byPriorityDesc);
  const showDelete = canDelete && !group.is_system;
  // A group/segment absent from its array means 0 members (see
  // `MemberCounts`'s docstring) — but only once counts are known at all;
  // `memberCounts === null` means "unknown", not "zero", so this stays
  // `null` in that case rather than falling back to a misleading 0.
  const groupUserCount = memberCounts
    ? (memberCounts.groups.find((g) => g.group_id === group.id)?.distinct_users ?? 0)
    : null;
  // One extra "Members" column when counts are available.
  const columnCount = memberCounts ? 7 : 6;

  const onDeleteGroup = async () => {
    setDeleting(true);
    const res = await deleteSegmentGroupAction(group.id, tenantId);
    setDeleting(false);
    setConfirmDelete(false);
    if (res.ok) {
      toast({ title: "Group deleted", description: group.name });
    } else {
      toast({
        title: "Couldn't delete",
        description: `${res.errorCode}: ${res.message}`,
        variant: "danger",
      });
    }
  };

  const onAddUser = async (segmentId: string, segTenantId: string, userId: string) => {
    if (!userId.trim()) return;
    setPending(segmentId);
    const res = await addUserToSegmentAction(segmentId, segTenantId, userId.trim());
    setPending(null);
    if (res.ok) {
      // Only a success clears the prompt — a rejected user id (typo'd UUID,
      // already-a-member, etc.) is exactly when the admin most needs the
      // row to stay open with what they typed still in the box, so they can
      // fix it and retry instead of re-opening the prompt from scratch.
      setUserIdPrompt(null);
      toast({ title: "User added to segment" });
    } else {
      toast({
        title: "Couldn't add",
        description: `${res.errorCode}: ${res.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="glass-panel mb-4 overflow-hidden rounded-lg">
      <div className="flex items-center gap-2 p-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="flex flex-1 items-center gap-2 text-left"
        >
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="font-medium">{group.name}</span>
          {group.is_system && <Badge variant="secondary">System</Badge>}
          <span className="text-xs text-muted-foreground">
            {sorted.length} segment{sorted.length === 1 ? "" : "s"}
            {groupUserCount !== null && (
              <> · {groupUserCount} user{groupUserCount === 1 ? "" : "s"}</>
            )}
          </span>
          {group.description && (
            <span className="hidden truncate text-xs text-muted-foreground sm:block">
              {group.description}
            </span>
          )}
        </button>
        {showDelete && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Delete group"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        )}
      </div>

      {open && (
        <div id={bodyId}>
          {sorted.length === 0 ? (
            <div className="border-t px-3 py-6 text-center text-sm text-muted-foreground">
              No segments in this group yet.
            </div>
          ) : (
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Type</TableHeaderCell>
                  <TableHeaderCell>Criteria</TableHeaderCell>
                  <TableHeaderCell>Priority</TableHeaderCell>
                  {memberCounts && <TableHeaderCell>Members</TableHeaderCell>}
                  <TableHeaderCell>Last evaluated</TableHeaderCell>
                  <TableHeaderCell className="w-[90px]">
                    <span className="sr-only">Actions</span>
                  </TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {sorted.map((s) => {
                  const isDynamic = s.criteria != null;
                  const text = criteriaText(s);
                  // Absent from `memberCounts.segments` -> 0 members (see
                  // `SegmentMemberCount`'s docstring), not "unknown" — the
                  // whole column is already hidden above when counts as a
                  // whole are unavailable.
                  const counts = memberCounts?.segments.find((c) => c.segment_id === s.id);
                  const total = counts?.total ?? 0;
                  const manual = counts?.manual ?? 0;
                  const criteriaCount = counts?.criteria ?? 0;
                  return (
                    <React.Fragment key={s.id}>
                      <TableRow>
                        <TableCell className="font-medium">
                          <span className="inline-flex items-center gap-1.5">
                            {s.name}
                            {s.is_system && <Badge variant="secondary">System</Badge>}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge variant={isDynamic ? "info" : "secondary"}>
                            {isDynamic ? "Dynamic" : "Static"}
                          </Badge>
                        </TableCell>
                        <TableCell
                          className="max-w-[220px] truncate text-sm text-muted-foreground"
                          title={text !== "—" ? text : undefined}
                        >
                          {text}
                        </TableCell>
                        <TableCell className="font-mono tabular-nums">{s.priority}</TableCell>
                        {memberCounts && (
                          <TableCell
                            className="tabular-nums"
                            title={`${manual} manual · ${criteriaCount} criteria`}
                          >
                            <div className="flex flex-col">
                              <span>{total}</span>
                              <span className="text-xs text-muted-foreground">
                                {manual} manual · {criteriaCount} criteria
                              </span>
                            </div>
                          </TableCell>
                        )}
                        <TableCell className="text-xs text-muted-foreground">
                          {lastEvaluatedText(s)}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            {/* Every segment is editable, including
                                is_system ones — only a GROUP MOVE is
                                blocked for those (enforced inside the
                                dialog itself, not by hiding this button). */}
                            <EditSegmentDialog
                              segment={s}
                              tenantId={tenantId}
                              groups={groups}
                              metrics={metrics}
                              services={services}
                            />
                            {!isDynamic && (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label="Assign user"
                                disabled={pending === s.id}
                                onClick={() => setUserIdPrompt({ segmentId: s.id, value: "" })}
                              >
                                <UserPlus className="h-3.5 w-3.5 text-primary" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                      {userIdPrompt?.segmentId === s.id && (
                        <TableRow>
                          <TableCell colSpan={columnCount} className="bg-muted/30">
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-muted-foreground">User ID:</span>
                              <Input
                                autoFocus
                                value={userIdPrompt.value}
                                onChange={(e) =>
                                  setUserIdPrompt({ ...userIdPrompt, value: e.target.value })
                                }
                                onKeyDown={(e) => {
                                  if (e.key === "Enter")
                                    onAddUser(s.id, s.tenant_id, userIdPrompt.value);
                                  if (e.key === "Escape") setUserIdPrompt(null);
                                }}
                                placeholder="00000000-…"
                                className="max-w-sm font-mono text-xs"
                              />
                              <Button
                                size="sm"
                                onClick={() => onAddUser(s.id, s.tenant_id, userIdPrompt.value)}
                                disabled={pending === s.id}
                              >
                                Assign
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => setUserIdPrompt(null)}
                              >
                                Cancel
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </React.Fragment>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </div>
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              Delete group?
            </DialogTitle>
            <DialogDescription>
              <strong>{group.name}</strong> will be permanently removed. This
              only succeeds while the group is empty — remove or move its
              segments first if it fails.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={onDeleteGroup} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
