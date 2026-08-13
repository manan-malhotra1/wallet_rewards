/**
 * Shared segment + segment-group fixtures for the campaigns component
 * tests. Two groups with segments (Customer Loyalty → Gold/Silver,
 * Transaction Value → High Rollers) plus one empty group, so cascade
 * tests can assert group filtering and the disabled empty-group state.
 * Not a test file — no `.test.` in the name, vitest never collects it.
 */
import type { Segment, SegmentGroup } from "@/lib/api-types";

function makeGroup(id: string, name: string): SegmentGroup {
  return {
    id,
    tenant_id: "tenant-1",
    name,
    description: null,
    is_system: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  };
}

function makeSegment(id: string, group_id: string, name: string): Segment {
  return {
    id,
    tenant_id: "tenant-1",
    name,
    description: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    group_id,
    priority: 0,
    criteria: null,
    is_system: false,
    last_evaluated_at: null,
  };
}

export const SEGMENT_GROUPS: SegmentGroup[] = [
  makeGroup("grp-loyalty", "Customer Loyalty"),
  makeGroup("grp-value", "Transaction Value"),
  makeGroup("grp-empty", "Empty Lens"),
];

export const SEGMENTS: Segment[] = [
  makeSegment("seg-gold", "grp-loyalty", "Gold"),
  makeSegment("seg-silver", "grp-loyalty", "Silver"),
  makeSegment("seg-high", "grp-value", "High Rollers"),
];
