/**
 * <EditSegmentDialog> — form for PATCH /segments/{id} (Segmentation Phase 1
 * Task 11 fix round): the "criteria editable in UI" promise from the spec.
 *
 * Prefills from the `segment` prop and submits ONLY the fields that changed
 * (compared against that same prop) — the backend's `update_segment` audits
 * exactly the changed fields, so a payload padded with unchanged values
 * would blur that audit trail with false "changes". A segment that started
 * dynamic (`criteria != null`) shows its criteria prefilled in
 * `<CriteriaBuilder>` plus a "Convert to static" checkbox that sends
 * `clear_criteria: true` instead of a `criteria` payload; a segment that
 * started static shows a "Dynamic segment" checkbox to add criteria for the
 * first time. Moving to a different group is blocked for `is_system`
 * segments (the backend 409s a real move attempt) — the Select is disabled
 * with an explanatory hint rather than letting the admin hit that error.
 */
"use client";

import { Pencil } from "lucide-react";
import * as React from "react";

import {
  previewCriteriaAction,
  updateSegmentAction,
} from "@/app/(authenticated)/segments/_actions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import type { UpdateSegmentPayload } from "@/lib/api-endpoints";
import type { Segment, SegmentCriteriaDoc, SegmentGroup, SegmentMetricInfo, Service } from "@/lib/api-types";
import { emptyCriteria, validateCriteria } from "@/lib/segment-criteria";

import { CriteriaBuilder } from "./criteria-builder";

interface FormState {
  description: string;
  groupId: string;
  priority: string;
  criteria: SegmentCriteriaDoc;
  // Only meaningful when the segment started dynamic — "turn this back
  // into a static segment" (sends `clear_criteria: true`).
  clearCriteria: boolean;
  // Only meaningful when the segment started static — "give this segment
  // criteria for the first time" (mounts the builder, starts empty).
  addDynamic: boolean;
}

function initialState(segment: Segment): FormState {
  return {
    description: segment.description ?? "",
    groupId: segment.group_id,
    priority: String(segment.priority),
    criteria: segment.criteria ?? emptyCriteria(),
    clearCriteria: false,
    addDynamic: false,
  };
}

export function EditSegmentDialog({
  segment,
  tenantId,
  groups,
  metrics,
  services,
}: {
  segment: Segment;
  tenantId: string;
  groups: SegmentGroup[];
  metrics: SegmentMetricInfo[];
  services: Service[];
}) {
  const wasDynamic = segment.criteria != null;
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() => initialState(segment));
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [previewCount, setPreviewCount] = React.useState<number | null>(null);
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewing, setPreviewing] = React.useState(false);
  const { toast } = useToast();

  // Every close path (Radix, Cancel, a successful submit) routes through
  // here so the form always resets to the segment's CURRENT values without
  // a `useEffect` watching `open` (see create-group-dialog.tsx's fix-round
  // note on why that trips react-hooks/set-state-in-effect for no benefit
  // over doing the reset here).
  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setForm(initialState(segment));
      setError(null);
      setPreviewCount(null);
      setPreviewError(null);
    }
  };

  // Whether the criteria builder is on screen at all — a dynamic segment
  // shows it unless the admin is converting to static; a static segment
  // shows it only once the admin opts in via "Dynamic segment".
  const showCriteriaBuilder = wasDynamic ? !form.clearCriteria : form.addDynamic;
  const criteriaErrors = showCriteriaBuilder ? validateCriteria(form.criteria) : [];

  const setCriteria = (criteria: SegmentCriteriaDoc) => {
    setForm((prev) => ({ ...prev, criteria }));
    setPreviewCount(null);
    setPreviewError(null);
  };

  const onPreview = async () => {
    setPreviewError(null);
    setPreviewing(true);
    const res = await previewCriteriaAction(tenantId, form.criteria);
    setPreviewing(false);
    if (res.ok) {
      setPreviewCount(res.count);
    } else {
      setPreviewError(`${res.errorCode}: ${res.message}`);
    }
  };

  const onSubmit = async () => {
    setError(null);
    if (form.priority.trim() === "") {
      setError("Priority is required.");
      return;
    }
    const priority = Number(form.priority);
    if (!Number.isInteger(priority) || priority < 0 || priority > 1000) {
      setError("Priority must be a whole number between 0 and 1000.");
      return;
    }
    if (showCriteriaBuilder && criteriaErrors.length > 0) {
      setError(criteriaErrors[0]);
      return;
    }

    // Diff against `segment` — only a field that actually changed goes into
    // the payload, so the backend's per-field audit row reflects a real
    // edit rather than every field the form happened to carry.
    const payload: UpdateSegmentPayload = {};

    const trimmedDescription = form.description.trim();
    const currentDescription = segment.description ?? "";
    if (trimmedDescription !== currentDescription) {
      payload.description = trimmedDescription === "" ? null : trimmedDescription;
    }

    if (priority !== segment.priority) {
      payload.priority = priority;
    }

    // The Select is disabled for an is_system segment (see render below), so
    // `form.groupId` can never actually differ for one — this check is
    // still explicit rather than relied-upon-implicitly, in case that ever
    // changes.
    if (!segment.is_system && form.groupId !== segment.group_id) {
      payload.group_id = form.groupId;
    }

    if (wasDynamic && form.clearCriteria) {
      payload.clear_criteria = true;
    } else if (showCriteriaBuilder && JSON.stringify(form.criteria) !== JSON.stringify(segment.criteria)) {
      payload.criteria = form.criteria;
    }

    if (Object.keys(payload).length === 0) {
      setError("No changes to save.");
      return;
    }

    setSubmitting(true);
    const res = await updateSegmentAction(segment.id, tenantId, payload);
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Segment updated", description: segment.name });
      onOpenChange(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Edit segment">
          <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit segment</DialogTitle>
          <DialogDescription>{segment.name}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="edit-seg-desc">Description (optional)</Label>
              <Input
                id="edit-seg-desc"
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="edit-seg-priority">Priority</Label>
              <Input
                id="edit-seg-priority"
                type="number"
                min="0"
                max="1000"
                value={form.priority}
                onChange={(e) => setForm((prev) => ({ ...prev, priority: e.target.value }))}
                className="mt-1 font-mono tabular-nums"
              />
            </div>
          </div>

          <div>
            <Label htmlFor="edit-seg-group">Group</Label>
            <div className="mt-1">
              <Select
                value={form.groupId}
                onValueChange={(v) => setForm((prev) => ({ ...prev, groupId: v }))}
                disabled={segment.is_system}
              >
                <SelectTrigger id="edit-seg-group">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {segment.is_system && (
              <p className="mt-1 text-xs text-muted-foreground">
                System segments stay in their seeded group — the backend rejects a move.
              </p>
            )}
          </div>

          {wasDynamic ? (
            <Checkbox
              checked={form.clearCriteria}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, clearCriteria: e.target.checked }))
              }
              label="Convert to static (clear criteria)"
            />
          ) : (
            <Checkbox
              checked={form.addDynamic}
              onChange={(e) => setForm((prev) => ({ ...prev, addDynamic: e.target.checked }))}
              label="Dynamic segment (criteria-based)"
            />
          )}

          {showCriteriaBuilder && (
            <div className="space-y-2 rounded-md border border-dashed p-3">
              <CriteriaBuilder
                value={form.criteria}
                metrics={metrics}
                services={services}
                onChange={setCriteria}
              />
              {criteriaErrors.length === 0 && (
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={onPreview}
                    disabled={previewing}
                  >
                    {previewing ? "Previewing…" : "Preview matches"}
                  </Button>
                  {previewCount !== null && (
                    <span className="text-xs text-muted-foreground">
                      ~{previewCount} users match
                    </span>
                  )}
                </div>
              )}
              {previewError && (
                <ErrorBanner title="Couldn't preview" description={previewError} />
              )}
            </div>
          )}

          {wasDynamic && form.clearCriteria && (
            <p className="text-xs text-muted-foreground">
              Existing memberships stay as-is — clearing criteria stops the evaluator
              from refreshing them, it doesn't remove current members.
            </p>
          )}

          {error && <ErrorBanner title="Couldn't update" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
