/**
 * Tests for the Approvals toolbar client-facet helpers. These are the pure
 * core behind the client-side facets (type, date) applied to the
 * server-fetched window: multi-type OR, the inclusive date-range boundary,
 * and default-tab resolution. (Status and search are server params — see
 * approvals-window.test.ts.)
 */
import { describe, expect, it } from "vitest";

import {
  applyFilters,
  DEFAULT_FILTERS,
  dateRangeCutoff,
  resolveActiveTab,
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

  it("Verify rows are never filtered by status (status is a server param)", () => {
    const out = applyFilters(rows, filters(), NOW);
    expect(out).toHaveLength(3);
  });

  it("Verify multiple selected types are OR-matched", () => {
    const out = applyFilters(rows, filters({ types: ["pricing", "tax"] }), NOW);
    expect(out.map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("Verify an empty type selection matches every type", () => {
    const out = applyFilters(rows, filters({ types: [] }), NOW);
    expect(out).toHaveLength(3);
  });

  it("Verify a facet-less (null type) row is excluded once any type is selected", () => {
    const withNull = [...rows, row({ id: "d", status: "PENDING", type: null })];
    const out = applyFilters(withNull, filters({ types: ["pricing"] }), NOW);
    expect(out.map((r) => r.id)).toEqual(["a"]);
  });

  it("Verify the facets combine (type AND date)", () => {
    const stale = new Date(NOW);
    stale.setDate(stale.getDate() - 60);
    const withStale = [...rows, row({ id: "d", type: "commission", createdAt: stale.toISOString() })];
    const out = applyFilters(
      withStale,
      filters({ types: ["commission"], dateRange: "30d" }),
      NOW,
    );
    expect(out.map((r) => r.id)).toEqual(["c"]);
  });

  it("Verify a combined filter can narrow to nothing", () => {
    const stale = new Date(NOW);
    stale.setDate(stale.getDate() - 60);
    const out = applyFilters(
      [row({ id: "old", type: "commission", createdAt: stale.toISOString() })],
      filters({ types: ["commission"], dateRange: "7d" }),
      NOW,
    );
    expect(out).toHaveLength(0);
  });
});

describe("resolveActiveTab — landing the checker where the work is", () => {
  const tabs = [
    { key: "configuration", pending: 0 },
    { key: "transactions", pending: 0 },
    { key: "users", pending: 1 },
  ];

  it("Verify the default tab is the first queue with pending items", () => {
    expect(resolveActiveTab(tabs, undefined)).toBe("users");
  });

  it("Verify an explicit ?tab= request wins over pending counts", () => {
    expect(resolveActiveTab(tabs, "configuration")).toBe("configuration");
  });

  it("Verify an unknown ?tab= falls back to the pending-first default", () => {
    expect(resolveActiveTab(tabs, "nonsense")).toBe("users");
  });

  it("Verify the earliest pending queue wins when several have work", () => {
    expect(
      resolveActiveTab(
        [
          { key: "configuration", pending: 0 },
          { key: "transactions", pending: 2 },
          { key: "users", pending: 5 },
        ],
        undefined,
      ),
    ).toBe("transactions");
  });

  it("Verify nothing pending anywhere lands on the first visible tab", () => {
    expect(
      resolveActiveTab(
        [
          { key: "configuration", pending: 0 },
          { key: "users", pending: 0 },
        ],
        undefined,
      ),
    ).toBe("configuration");
  });

  it("Verify no visible tabs resolves to null", () => {
    expect(resolveActiveTab([], undefined)).toBeNull();
  });
});
