/**
 * <EditCampaignDialog> — patch a campaign's editable fields.
 *
 * Trigger conditions (rule_type, transaction_type, count_threshold,
 * min_amount, etc.) are intentionally read-only — they're load-bearing
 * for in-flight `user_rule_progress`. Operators wanting to change them
 * should deactivate this campaign and create a new one.
 *
 * Audience targeting (WAL-79) IS editable: the segment binding is an
 * eligibility gate checked at evaluation time, not a trigger condition,
 * so retargeting never corrupts in-flight progress. The payload carries
 * `segment_id` only when the operator actually changed it — an explicit
 * null clears the binding (back to all users).
 */
"use client";

import * as React from "react";

import { updateCampaignAction } from "@/app/(authenticated)/campaigns/_actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
import type { Rule, Segment, SegmentGroup } from "@/lib/api-types";

import { ALL_USERS, SegmentTargetPicker } from "./segment-target-picker";

/** The group a rule's current segment binding lives in, or the ALL sentinel. */
function groupOfSegment(segments: Segment[], segmentId: string | null | undefined): string {
  if (!segmentId) return ALL_USERS;
  return segments.find((s) => s.id === segmentId)?.group_id ?? ALL_USERS;
}

export function EditCampaignDialog({
  rule,
  tenantId,
  segments,
  segmentGroups,
  open,
  onOpenChange,
}: {
  rule: Rule;
  tenantId: string;
  segments: Segment[];
  segmentGroups: SegmentGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = React.useState(rule.name);
  const [rewardValue, setRewardValue] = React.useState(String(rule.reward_value));
  const [status, setStatus] = React.useState<"active" | "inactive">(
    (rule.status as "active" | "inactive") ?? "active",
  );
  const [groupId, setGroupId] = React.useState(groupOfSegment(segments, rule.segment_id));
  const [segmentId, setSegmentId] = React.useState(rule.segment_id ?? "");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (open) {
      setName(rule.name);
      setRewardValue(String(rule.reward_value));
      setStatus((rule.status as "active" | "inactive") ?? "active");
      setGroupId(groupOfSegment(segments, rule.segment_id));
      setSegmentId(rule.segment_id ?? "");
      setError(null);
    }
  }, [open, rule, segments]);

  const onSubmit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    const reward = Number(rewardValue);
    if (!Number.isFinite(reward) || reward <= 0) {
      setError("Reward value must be a positive number.");
      return;
    }
    // A group without a segment is an incomplete target — refuse rather
    // than silently widening the campaign back to everyone.
    if (groupId !== ALL_USERS && !segmentId) {
      setError(
        "Choose a segment in the selected group, or set the target audience to All users.",
      );
      return;
    }
    const targetChanged = (segmentId || null) !== (rule.segment_id ?? null);
    setSubmitting(true);
    const result = await updateCampaignAction(rule.id, tenantId, {
      name: name.trim(),
      reward_value: rewardValue,
      status,
      // Only send targeting when it changed: an explicit null CLEARS the
      // binding on the backend, so an untouched field must stay omitted.
      ...(targetChanged ? { segment_id: segmentId || null } : {}),
    });
    setSubmitting(false);
    if (result.ok) {
      toast({ title: "Campaign updated" });
      onOpenChange(false);
    } else {
      setError(`${result.errorCode}: ${result.message}`);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit campaign</DialogTitle>
          <DialogDescription>
            Editable: name, reward value, status, target audience. Trigger
            conditions are locked once a campaign is live — deactivate this
            one and create a new one if those need to change.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="edit-name">Name</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="edit-reward">Reward value ({rule.reward_type})</Label>
            <Input
              id="edit-reward"
              type="number"
              step="0.01"
              min="0.01"
              value={rewardValue}
              onChange={(e) => setRewardValue(e.target.value)}
              className="mt-1 tabular-nums"
            />
          </div>
          <SegmentTargetPicker
            groups={segmentGroups}
            segments={segments}
            groupId={groupId}
            segmentId={segmentId}
            onGroupChange={setGroupId}
            onSegmentChange={setSegmentId}
          />
          <div>
            <Label>Status</Label>
            <Select
              value={status}
              onValueChange={(v) => setStatus(v as "active" | "inactive")}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active — firing</SelectItem>
                <SelectItem value="inactive">Inactive — paused</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <ErrorBanner title="Couldn't save" description={error} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Saving…" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
