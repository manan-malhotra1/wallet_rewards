/**
 * Tests for the Approvals toolbar filter/count helpers. These are the pure
 * core behind every facet, so they carry the coverage for the whole toolbar:
 * status tallies, multi-type OR, the inclusive date-range boundary, search
 * across maker/entity/request-id, and the composed "X of Y" derivation.
 */
import { describe, expect, it } from "vitest";

import {
  applyFilters,
  countByStatus,
  DEFAULT_FILTERS,
  dateRangeCutoff,
  matchesSearch,
  summarize,
  withinDateRange,
  type ApprovalFilters,
  type ApprovalRow,
} from "@/lib/approvals-filter";

/** Fixed reference "now" so date-range tests never depend on the wall clock. */
const NOW = new Date("2026-08-03T12:00:00Z");

/** Minimal ApprovalRow factory — every field defaulted, override what a test needs. */
function row(overrides: Partial<ApprovalRow> = {}): ApprovalRow {
  return {
    id: "req-1",
    status: "PENDING",
    type: "pricing",
    createdAt: NOW.toISOString(),
    maker: "Alice Smith",
    makerId: "admin-alice",
    summary: "Service charge → p2p",
    ...overrides,
  };
}

/** Merge a partial selection onto the defaults for concise filter setup. */
function filters(overrides: Partial<ApprovalFilters> = {}): ApprovalFilters {
  return { ...DEFAULT_FILTERS, ...overrides };
}

describe("countByStatus", () => {
  it("Verify an empty queue reports every status and the total as zero", () => {
    expect(countByStatus([])).toEqual({
      PENDING: 0,
      CHANGES_REQUESTED: 0,
      APPLIED: 0,
      WITHDRAWN: 0,
      ALL: 0,
    });
  });

  it("Verify a mixed queue tallies each status and sums them into the All total", () => {
    const rows = [
      row({ status: "PENDING" }),
      row({ status: "PENDING" }),
      row({ status: "APPLIED" }),
      row({ status: "WITHDRAWN" }),
      row({ status: "CHANGES_REQUESTED" }),
    ];
    const counts = countByStatus(rows);
    expect(counts.PENDING).toBe(2);
    expect(counts.APPLIED).toBe(1);
    expect(counts.WITHDRAWN).toBe(1);
    expect(counts.CHANGES_REQUESTED).toBe(1);
    expect(counts.ALL).toBe(5);
  });

  it("Verify an unrecognised status is counted in the total but never mis-bucketed", () => {
    const counts = countByStatus([row({ status: "SOMETHING_NEW" })]);
    expect(counts.ALL).toBe(1);
    expect(counts.PENDING).toBe(0);
  });
});

describe("matchesSearch", () => {
  const r = row({
    id: "req-abc123",
    maker: "Bob Jones",
    makerId: "admin-bob",
    summary: "Fund user → Carol",
  });

  it("Verify an empty query keeps every row", () => {
    expect(matchesSearch(r, "")).toBe(true);
    expect(matchesSearch(r, "   ")).toBe(true);
  });

  it("Verify a search matches the maker name case-insensitively", () => {
    expect(matchesSearch(r, "bob jones")).toBe(true);
    expect(matchesSearch(r, "JONES")).toBe(true);
  });

  it("Verify a search matches the raw maker id even when a name is displayed", () => {
    expect(matchesSearch(r, "admin-bob")).toBe(true);
  });

  it("Verify a search matches the entity/summary text", () => {
    expect(matchesSearch(r, "carol")).toBe(true);
  });

  it("Verify a search matches a partial request id", () => {
    expect(matchesSearch(r, "abc123")).toBe(true);
  });

  it("Verify an unrelated query keeps no row", () => {
    expect(matchesSearch(r, "zzz-nope")).toBe(false);
  });
});

describe("date range", () => {
  it("Verify the All-time preset applies no lower bound", () => {
    expect(dateRangeCutoff("all", NOW)).toBeNull();
    expect(withinDateRange(row({ createdAt: "2000-01-01T00:00:00Z" }), "all", NOW)).toBe(true);
  });

  it("Verify a row exactly on the range boundary is kept (inclusive cutoff)", () => {
    // 30 days before NOW, to the millisecond.
    const boundary = new Date(NOW);
    boundary.setDate(boundary.getDate() - 30);
    expect(withinDateRange(row({ createdAt: boundary.toISOString() }), "30d", NOW)).toBe(true);
  });

  it("Verify a row just outside the range is dropped", () => {
    const tooOld = new Date(NOW);
    tooOld.setDate(tooOld.getDate() - 31);
    expect(withinDateRange(row({ createdAt: tooOld.toISOString() }), "30d", NOW)).toBe(false);
  });

  it("Verify a row inside the range is kept", () => {
    const recent = new Date(NOW);
    recent.setDate(recent.getDate() - 3);
    expect(withinDateRange(row({ createdAt: recent.toISOString() }), "7d", NOW)).toBe(true);
  });

  it("Verify an unparseable timestamp is dropped by a bounded preset", () => {
    expect(withinDateRange(row({ createdAt: "not-a-date" }), "7d", NOW)).toBe(false);
  });
});

describe("applyFilters", () => {
  const rows = [
    row({ id: "a", status: "PENDING", type: "pricing", createdAt: NOW.toISOString() }),
    row({ id: "b", status: "APPLIED", type: "tax", createdAt: NOW.toISOString() }),
    row({ id: "c", status: "PENDING", type: "commission", createdAt: NOW.toISOString() }),
  ];

  it("Verify a status filter keeps only rows in that status", () => {
    const out = applyFilters(rows, filters({ status: "PENDING" }), NOW);
    expect(out.map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("Verify selecting All status skips the status filter", () => {
    const out = applyFilters(rows, filters({ status: "ALL" }), NOW);
    expect(out).toHaveLength(3);
  });

  it("Verify multiple selected types are OR-matched", () => {
    const out = applyFilters(
      rows,
      filters({ status: "ALL", types: ["pricing", "tax"] }),
      NOW,
    );
    expect(out.map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("Verify an empty type selection matches every type", () => {
    const out = applyFilters(rows, filters({ status: "ALL", types: [] }), NOW);
    expect(out).toHaveLength(3);
  });

  it("Verify a facet-less (null type) row is excluded once any type is selected", () => {
    const withNull = [...rows, row({ id: "d", status: "PENDING", type: null })];
    const out = applyFilters(
      withNull,
      filters({ status: "ALL", types: ["pricing"] }),
      NOW,
    );
    expect(out.map((r) => r.id)).toEqual(["a"]);
  });

  it("Verify the facets combine (status AND type AND search)", () => {
    const out = applyFilters(
      rows,
      filters({ status: "PENDING", types: ["commission"], q: "service charge" }),
      NOW,
    );
    expect(out.map((r) => r.id)).toEqual(["c"]);
  });

  it("Verify a combined filter can narrow to nothing", () => {
    const out = applyFilters(
      rows,
      filters({ status: "APPLIED", types: ["commission"] }),
      NOW,
    );
    expect(out).toHaveLength(0);
  });
});

describe("summarize (X of Y + segment counts)", () => {
  const rows = [
    row({ id: "a", status: "PENDING", type: "pricing" }),
    row({ id: "b", status: "PENDING", type: "tax" }),
    row({ id: "c", status: "APPLIED", type: "pricing" }),
    row({ id: "d", status: "WITHDRAWN", type: "pricing" }),
  ];

  it("Verify X is the fully-filtered count and Y is the untouched tab total", () => {
    const { shown, total } = summarize(rows, filters({ status: "PENDING" }), NOW);
    expect(shown).toBe(2);
    expect(total).toBe(4);
  });

  it("Verify segment counts reflect the other facets but not the chosen status", () => {
    // Type=pricing narrows the pool to a, c, d; the status segments count that pool.
    const { statusCounts, shown } = summarize(
      rows,
      filters({ status: "PENDING", types: ["pricing"] }),
      NOW,
    );
    expect(statusCounts.ALL).toBe(3); // a, c, d
    expect(statusCounts.PENDING).toBe(1); // a
    expect(statusCounts.APPLIED).toBe(1); // c
    expect(statusCounts.WITHDRAWN).toBe(1); // d
    // The table shows only the pending pricing row.
    expect(shown).toBe(1);
  });

  it("Verify selecting All status shows the whole pool", () => {
    const { shown, total } = summarize(rows, filters({ status: "ALL" }), NOW);
    expect(shown).toBe(4);
    expect(total).toBe(4);
  });
});
