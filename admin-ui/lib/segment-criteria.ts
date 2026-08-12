/**
 * Pure helpers for the dynamic-segment criteria builder (Segmentation Phase
 * 1): construct an empty criteria document, render it as a human-readable
 * summary, and mirror the backend DSL's structural validation client-side so
 * the admin sees a rejection before submitting (the backend, `criteria.py`'s
 * `Condition._check_shape`, is still the source of truth and re-validates).
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
 */
export function summarizeCriteria(doc: SegmentCriteriaDoc): string {
  if (doc.conditions.length === 0) return "No conditions yet.";
  return doc.conditions.map(formatCondition).join(` ${doc.op} `);
}

/** True when a comparator field (gte/lte/eq) is present (not undefined/null). */
function isSet(value: number | null | undefined): value is number {
  return value !== undefined && value !== null;
}

/**
 * Validate a criteria document against the same structural rules the
 * backend's `Condition._check_shape` enforces, so the admin sees a clear
 * rejection before submitting.
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

  doc.conditions.forEach((condition, index) => {
    const n = index + 1;
    const hasGte = isSet(condition.gte);
    const hasLte = isSet(condition.lte);
    const hasEq = isSet(condition.eq);

    if (!hasGte && !hasLte && !hasEq) {
      errors.push(`Condition ${n} needs a threshold (≥, ≤ or =).`);
      return;
    }
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
  });

  return errors;
}
