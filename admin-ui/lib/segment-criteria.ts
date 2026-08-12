/**
 * Pure helpers for the dynamic-segment criteria builder (Segmentation Phase
 * 1): construct an empty criteria document, render it as a human-readable
 * summary, and check a client-side SUBSET of the backend DSL's structural
 * validation so the admin sees a rejection before submitting (the backend,
 * `criteria.py`'s `Condition._check_shape`, is still the source of truth and
 * re-validates independently — see `validateCriteria`'s docstring for
 * exactly what's checked here vs. left to the backend).
 */
import type { CriteriaCondition, SegmentCriteriaDoc } from "@/lib/api-types";

/** A fresh, empty criteria document — the criteria builder's starting state. */
export function emptyCriteria(): SegmentCriteriaDoc {
  return { v: 1, op: "AND", conditions: [] };
}

/** Render a condition's optional txn_type/window_days filters as "(p2p, last 90d)", or "" when neither is set. */
function formatFilters(condition: CriteriaCondition): string {
  const parts: string[] = [];
  if (condition.txn_type) parts.push(condition.txn_type);
  if (condition.window_days != null) parts.push(`last ${condition.window_days}d`);
  return parts.length ? ` (${parts.join(", ")})` : "";
}

/** Render one condition as "metric (filters) ≥ value", picking the comparator that's set. */
function formatCondition(condition: CriteriaCondition): string {
  const label = `${condition.metric}${formatFilters(condition)}`;
  if (condition.eq != null) return `${label} = ${condition.eq}`;
  if (condition.gte != null && condition.lte != null) {
    return `${condition.gte} ≤ ${label} ≤ ${condition.lte}`;
  }
  if (condition.gte != null) return `${label} ≥ ${condition.gte}`;
  if (condition.lte != null) return `${label} ≤ ${condition.lte}`;
  return label;
}

/**
 * Render a criteria document as a single human-readable line, e.g.
 * "txn_sum (p2p, last 90d) ≥ 5000 AND days_since_last_txn ≤ 14". Callers
 * should prefer `validateCriteria`'s errors over this when the document is
 * invalid — this function renders whatever is there without judging it.
 *
 * Defensive by necessity, not just by style: `Segment.criteria` (the usual
 * source of a `doc` here, once Task 11's table renders real rows) is typed
 * `SegmentCriteriaDoc | null` on the TypeScript side, but the backend's own
 * `SegmentOut.criteria` is a lenient `dict[str, Any] | None` that tolerates
 * legacy/poisoned rows the strict DSL schema no longer parses (see that
 * field's comment in api-types.ts). A poisoned row can reach this function
 * typed as `SegmentCriteriaDoc` while not actually having a `conditions`
 * array at runtime — the `Array.isArray` guard below is for THAT case, not
 * a redundant restatement of the compile-time type.
 */
export function summarizeCriteria(doc: SegmentCriteriaDoc): string {
  if (!Array.isArray(doc?.conditions) || doc.conditions.length === 0) {
    return "No conditions yet.";
  }
  return doc.conditions.map(formatCondition).join(` ${doc.op} `);
}

/** True when a comparator field (gte/lte/eq) is present (not undefined/null). */
function isSet(value: number | null | undefined): value is number {
  return value !== undefined && value !== null;
}

/**
 * Validate a criteria document against a CLIENT-SIDE SUBSET of the rules the
 * backend's `Condition._check_shape` (plus `SegmentCriteria`'s field
 * constraints) enforce — a deliberate subset, not a full mirror, so the
 * admin sees a clear rejection before submitting. The backend re-validates
 * independently regardless; never trust the client.
 *
 * Checked here:
 *   - 1-10 conditions (`SegmentCriteria.conditions` min_length=1, max_length=10).
 *   - each condition has at least one comparator (gte/lte/eq).
 *   - `eq` is not combined with `gte`/`lte`.
 *   - `gte` does not exceed `lte`.
 *   - every set threshold (gte/lte/eq) is >= 0.
 *   - `window_days`, when set, is a whole number in [1, 365].
 *
 * Deliberately NOT re-checked here (backend-only) — the criteria builder
 * makes these structurally unreachable by construction, so duplicating the
 * check here would be dead code:
 *   - `metric` is a member of the DSL's `MetricName` vocabulary — the
 *     builder only ever offers metrics from `GET /segments/metrics`, so an
 *     unknown metric can't be selected through this UI.
 *   - `txn_type`/`window_days` are only set on a metric that supports them
 *     — the builder clears both when switching to a metric that doesn't
 *     (see `ConditionRow.setMetric` in criteria-builder.tsx), so that
 *     mismatch can't arise from interacting with this UI.
 *   - `txn_type` string length (1-50 chars) — the builder's txn_type values
 *     always come from the tenant's service codes, never free text.
 *
 * Returns:
 *   An empty array when the document is valid; otherwise one message per
 *   violation, 1-indexed by condition position for readability.
 */
export function validateCriteria(doc: SegmentCriteriaDoc): string[] {
  const errors: string[] = [];
  if (doc.conditions.length === 0) {
    errors.push("Add at least one condition.");
    return errors;
  }
  if (doc.conditions.length > 10) {
    errors.push("At most 10 conditions.");
  }

  doc.conditions.forEach((condition, index) => {
    const n = index + 1;
    const hasGte = isSet(condition.gte);
    const hasLte = isSet(condition.lte);
    const hasEq = isSet(condition.eq);

    if (!hasGte && !hasLte && !hasEq) {
      errors.push(`Condition ${n} needs a threshold (≥, ≤ or =).`);
    } else {
      if (hasEq && (hasGte || hasLte)) {
        errors.push(`Condition ${n}: = cannot be combined with ≥/≤.`);
      }
      if (hasGte && hasLte && condition.gte! > condition.lte!) {
        errors.push(`Condition ${n}: ≥ bound exceeds ≤ bound.`);
      }
      const thresholds = [condition.gte, condition.lte, condition.eq].filter(isSet);
      if (thresholds.some((value) => value < 0)) {
        errors.push(`Condition ${n}: thresholds must be ≥ 0.`);
      }
    }

    // Independent of the comparator checks above — a condition can have a
    // bad window_days regardless of whether its threshold is also invalid.
    if (isSet(condition.window_days)) {
      const window = condition.window_days;
      if (!Number.isInteger(window) || window < 1 || window > 365) {
        errors.push(
          `Condition ${n}: window must be a whole number of days between 1 and 365.`,
        );
      }
    }
  });

  return errors;
}
