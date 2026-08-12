/**
 * <CreateSegmentDialog> — form for POST /segments.
 *
 * Every segment belongs to exactly one group (the exclusive-tier "lens" it's
 * evaluated within) and carries a priority used to break ties within that
 * group. Checking "Dynamic segment" swaps membership from admin-assigned to
 * criteria-evaluated: the `<CriteriaBuilder>` mounts, and the payload's
 * `criteria` field is populated (and `validateCriteria` gates submit) only
 * while that box is checked — leaving it unchecked keeps today's static
 * (admin-assigned) behaviour, payload-compatible with the pre-Phase-1 form.
 */
"use client";

import * as React from "react";

import {
  createSegmentAction,
  previewCriteriaAction,
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
import type { SegmentCriteriaDoc, SegmentGroup, SegmentMetricInfo, Service } from "@/lib/api-types";
import { emptyCriteria, validateCriteria } from "@/lib/segment-criteria";

import { CriteriaBuilder } from "./criteria-builder";

interface FormState {
  name: string;
  description: string;
  groupId: string;
  priority: string;
  isDynamic: boolean;
  criteria: SegmentCriteriaDoc;
}

function initialState(firstGroupId: string): FormState {
  return {
    name: "",
    description: "",
    groupId: firstGroupId,
    priority: "0",
    isDynamic: false,
    criteria: emptyCriteria(),
  };
}

export function CreateSegmentDialog({
  tenantId,
  groups,
  metrics,
  services,
  trigger,
}: {
  tenantId: string;
  groups: SegmentGroup[];
  metrics: SegmentMetricInfo[];
  services: Service[];
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState<FormState>(() => initialState(groups[0]?.id ?? ""));
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [previewCount, setPreviewCount] = React.useState<number | null>(null);
  // Kept separate from `error` (the create-submit failure) so a preview
  // rejection renders under its own "Couldn't preview" banner rather than
  // stacking under — or being confused with — a create failure.
  const [previewError, setPreviewError] = React.useState<string | null>(null);
  const [previewing, setPreviewing] = React.useState(false);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialState(groups[0]?.id ?? ""));
      setError(null);
      setPreviewCount(null);
      setPreviewError(null);
    }
    // groups only changes on remount of the page, not while the dialog is
    // open — re-running this on `open` alone avoids resetting the form
    // mid-edit if the parent re-renders with a new groups array reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const criteriaErrors = form.isDynamic ? validateCriteria(form.criteria) : [];

  const setCriteria = (criteria: SegmentCriteriaDoc) => {
    setForm((prev) => ({ ...prev, criteria }));
    // A changed document invalidates any previously fetched match count (or
    // a previous preview failure — the admin is about to retry it fresh).
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
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (!form.groupId) {
      setError("Create a segment group first.");
      return;
    }
    // Number("") is 0 — an explicit emptiness check first, so a cleared
    // priority field is rejected rather than silently defaulting to 0.
    if (form.priority.trim() === "") {
      setError("Priority is required.");
      return;
    }
    const priority = Number(form.priority);
    if (!Number.isInteger(priority) || priority < 0 || priority > 1000) {
      setError("Priority must be a whole number between 0 and 1000.");
      return;
    }
    if (form.isDynamic && criteriaErrors.length > 0) {
      setError(criteriaErrors[0]);
      return;
    }
    setSubmitting(true);
    const res = await createSegmentAction({
      tenant_id: tenantId,
      group_id: form.groupId,
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      priority,
      criteria: form.isDynamic ? form.criteria : undefined,
    });
    setSubmitting(false);
    if (res.ok) {
      toast({ title: "Segment created", description: form.name });
      setOpen(false);
    } else {
      setError(`${res.errorCode}: ${res.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>New segment</DialogTitle>
          <DialogDescription>
            A cohort of users, static (admin-assigned) or dynamic (criteria-evaluated).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="seg-name">Name</Label>
              <Input
                id="seg-name"
                value={form.name}
                onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="vip-users"
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="seg-group">Group</Label>
              <div className="mt-1">
                <Select
                  value={form.groupId}
                  onValueChange={(v) => setForm((prev) => ({ ...prev, groupId: v }))}
                  disabled={groups.length === 0}
                >
                  <SelectTrigger id="seg-group">
                    <SelectValue placeholder="No groups yet" />
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
              {groups.length === 0 && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Create a segment group before a segment.
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="seg-desc">Description (optional)</Label>
              <Input
                id="seg-desc"
                value={form.description}
                onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                placeholder="Top 1% of customers by lifetime spend."
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="seg-priority">Priority</Label>
              <Input
                id="seg-priority"
                type="number"
                min="0"
                max="1000"
                value={form.priority}
                onChange={(e) => setForm((prev) => ({ ...prev, priority: e.target.value }))}
                className="mt-1 font-mono tabular-nums"
              />
            </div>
          </div>

          <Checkbox
            checked={form.isDynamic}
            onChange={(e) => setForm((prev) => ({ ...prev, isDynamic: e.target.checked }))}
            label="Dynamic segment (criteria-based)"
          />

          {form.isDynamic && (
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

          {error && <ErrorBanner title="Couldn't create" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
