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
import type { Segment, SegmentGroup } from "@/lib/api-types";
import { summarizeCriteria } from "@/lib/segment-criteria";
import { formatTimestamp } from "@/lib/utils";

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
  canDelete = true,
}: {
  group: SegmentGroup;
  segments: Segment[];
  tenantId: string;
  canDelete?: boolean;
}) {
  const [open, setOpen] = React.useState(true);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [pending, setPending] = React.useState<string | null>(null);
  const [userIdPrompt, setUserIdPrompt] = React.useState<{
    segmentId: string;
    tenantId: string;
    value: string;
  } | null>(null);
  const { toast } = useToast();

  const sorted = [...segments].sort(byPriorityDesc);
  const showDelete = canDelete && !group.is_system;

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
    setUserIdPrompt(null);
    if (res.ok) {
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
    <div className="mb-4 overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center gap-2 p-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
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

      {open &&
        (sorted.length === 0 ? (
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
                <TableHeaderCell>Last evaluated</TableHeaderCell>
                <TableHeaderCell className="w-[50px]">
                  <span className="sr-only">Actions</span>
                </TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sorted.map((s) => {
                const isDynamic = s.criteria != null;
                const text = criteriaText(s);
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
                      <TableCell className="text-xs text-muted-foreground">
                        {lastEvaluatedText(s)}
                      </TableCell>
                      <TableCell>
                        {!isDynamic && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Assign user"
                            disabled={pending === s.id}
                            onClick={() =>
                              setUserIdPrompt({
                                segmentId: s.id,
                                tenantId: s.tenant_id,
                                value: "",
                              })
                            }
                          >
                            <UserPlus className="h-3.5 w-3.5 text-primary" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {userIdPrompt?.segmentId === s.id && (
                      <TableRow>
                        <TableCell colSpan={6} className="bg-muted/30">
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
        ))}

      <Dialog open={confirmDelete} onOpenChange={(o) => !o && setConfirmDelete(false)}>
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
