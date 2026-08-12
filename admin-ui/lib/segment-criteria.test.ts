/**
 * Unit tests for the segment-criteria lib helpers — the pure functions
 * behind the criteria builder: constructing an empty document, rendering a
 * human summary, and mirroring the backend DSL's client-side validation.
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
});
