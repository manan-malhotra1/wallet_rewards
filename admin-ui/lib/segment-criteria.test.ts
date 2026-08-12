/**
 * Unit tests for the segment-criteria lib helpers — the pure functions
 * behind the criteria builder: constructing an empty document, rendering a
 * human summary (defensively, for poisoned/legacy rows), and checking a
 * client-side subset of the backend DSL's structural validation.
 */
import { describe, expect, it } from "vitest";

import { emptyCriteria, summarizeCriteria, validateCriteria } from "@/lib/segment-criteria";
import type { SegmentCriteriaDoc } from "@/lib/api-types";

describe("emptyCriteria — the criteria builder's starting document", () => {
  it("Verify a fresh document is an empty AND with no conditions", () => {
    expect(emptyCriteria()).toEqual({ v: 1, op: "AND", conditions: [] });
  });
});

describe("summarizeCriteria — human-readable rendering", () => {
  it("Verify a two-condition AND renders filters and comparators inline", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [
        { metric: "txn_sum", txn_type: "p2p", window_days: 90, gte: 5000 },
        { metric: "days_since_last_txn", lte: 14 },
      ],
    };
    expect(summarizeCriteria(doc)).toBe(
      "txn_sum (p2p, last 90d) ≥ 5000 AND days_since_last_txn ≤ 14",
    );
  });

  it("Verify an eq condition renders with the = sign", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "OR",
      conditions: [{ metric: "referral_count", eq: 3 }],
    };
    expect(summarizeCriteria(doc)).toBe("referral_count = 3");
  });

  it("Verify a zero minimum renders as '≥ 0', not as absent", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "referral_count", gte: 0 }],
    };
    expect(summarizeCriteria(doc)).toBe("referral_count ≥ 0");
  });

  it("Verify a poisoned/legacy row with no conditions array renders the empty-state text instead of throwing", () => {
    // Segment.criteria is typed SegmentCriteriaDoc but is, at the wire level,
    // the backend's lenient dict[str, Any] | None — a hand-edited or
    // pre-DSL row can reach here without a `conditions` array at all.
    const poisoned = { v: 1, op: "AND" } as unknown as SegmentCriteriaDoc;
    expect(summarizeCriteria(poisoned)).toBe("No conditions yet.");
  });
});

describe("validateCriteria — client-side mirror of the backend DSL rules", () => {
  it("Verify an empty document is rejected", () => {
    expect(validateCriteria(emptyCriteria())).toEqual([
      "Add at least one condition.",
    ]);
  });

  it("Verify a condition with no comparator is rejected", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_count" }],
    };
    expect(validateCriteria(doc)).toEqual([
      "Condition 1 needs a threshold (≥, ≤ or =).",
    ]);
  });

  it("Verify a fully valid document has no errors", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [
        { metric: "txn_sum", gte: 100 },
        { metric: "days_since_last_txn", lte: 30 },
      ],
    };
    expect(validateCriteria(doc)).toEqual([]);
  });

  it("Verify eq combined with gte is rejected", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_count", eq: 5, gte: 1 }],
    };
    expect(validateCriteria(doc)).toEqual([
      "Condition 1: = cannot be combined with ≥/≤.",
    ]);
  });

  it("Verify a gte bound exceeding the lte bound is rejected", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 100, lte: 50 }],
    };
    expect(validateCriteria(doc)).toEqual([
      "Condition 1: ≥ bound exceeds ≤ bound.",
    ]);
  });

  it("Verify a negative threshold is rejected", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: -10 }],
    };
    expect(validateCriteria(doc)).toEqual([
      "Condition 1: thresholds must be ≥ 0.",
    ]);
  });

  it("Verify a zero minimum is a valid threshold, not treated as absent", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "referral_count", gte: 0 }],
    };
    expect(validateCriteria(doc)).toEqual([]);
  });

  it("Verify more than 10 conditions is rejected", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: Array.from({ length: 11 }, () => ({ metric: "txn_count", gte: 1 })),
    };
    expect(validateCriteria(doc)).toContain("At most 10 conditions.");
  });

  it.each([
    [0, "Condition 1: window must be a whole number of days between 1 and 365."],
    [400, "Condition 1: window must be a whole number of days between 1 and 365."],
    [1.5, "Condition 1: window must be a whole number of days between 1 and 365."],
  ])("Verify an out-of-range or fractional window_days (%s) is rejected", (window_days, message) => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 1, window_days }],
    };
    expect(validateCriteria(doc)).toContain(message);
  });

  it("Verify a valid window_days (within 1-365, whole number) passes", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 1, window_days: 90 }],
    };
    expect(validateCriteria(doc)).toEqual([]);
  });
});
