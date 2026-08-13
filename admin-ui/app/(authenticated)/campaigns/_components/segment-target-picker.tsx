/**
 * <SegmentTargetPicker> — the two-level audience cascade for a campaign.
 *
 * First pick the segment group (the segmentation lens, e.g. Customer
 * Loyalty), then a segment inside it — the segment options are always
 * filtered to the chosen group. "All users" short-circuits both: no
 * segment binding is sent and the campaign targets everyone.
 *
 * Fully controlled: the parent form owns `groupId` ("all" sentinel) and
 * `segmentId` (""), so create + edit dialogs share the exact behaviour.
 * Choosing a new group resets the segment (a segment never belongs to
 * two groups). Empty groups are shown disabled rather than hidden so the
 * operator learns why a lens is unavailable.
 */
"use client";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Segment, SegmentGroup } from "@/lib/api-types";

/** Sentinel for the group select — no binding, campaign targets everyone. */
export const ALL_USERS = "all";

export function SegmentTargetPicker({
  groups,
  segments,
  groupId,
  segmentId,
  onGroupChange,
  onSegmentChange,
}: {
  groups: SegmentGroup[];
  segments: Segment[];
  /** Selected group id, or the `ALL_USERS` sentinel. */
  groupId: string;
  /** Selected segment id, or "" while none is chosen yet. */
  segmentId: string;
  onGroupChange: (groupId: string) => void;
  onSegmentChange: (segmentId: string) => void;
}) {
  const groupSegments = segments.filter((s) => s.group_id === groupId);

  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <Label htmlFor="segment-group">Target audience</Label>
        <Select
          value={groupId}
          onValueChange={(v) => {
            onGroupChange(v);
            // A segment never spans groups — a new lens invalidates the pick.
            onSegmentChange("");
          }}
        >
          <SelectTrigger id="segment-group" className="mt-1" aria-label="Segment group">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_USERS}>All users</SelectItem>
            {groups.map((g) => (
              <SelectItem
                key={g.id}
                value={g.id}
                disabled={!segments.some((s) => s.group_id === g.id)}
              >
                {g.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {groupId !== ALL_USERS && (
        <div>
          <Label htmlFor="segment-target">Segment</Label>
          <Select value={segmentId} onValueChange={onSegmentChange}>
            <SelectTrigger id="segment-target" className="mt-1" aria-label="Segment">
              <SelectValue placeholder="Choose a segment…" />
            </SelectTrigger>
            <SelectContent>
              {groupSegments.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  );
}
