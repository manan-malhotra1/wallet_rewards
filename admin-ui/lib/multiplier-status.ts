/**
 * Pure helpers for the bonus-multipliers page (Epic 10 / WAL-78): derive a
 * multiplier's lifecycle status from its validity window and render its
 * scope / window as human-readable labels.
 */
import type { BonusMultiplier } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/utils";

export type MultiplierStatus = "SCHEDULED" | "ACTIVE" | "EXPIRED";

/**
 * Derive the lifecycle status of a multiplier at `now`.
 *
 * Mirrors the backend's resolution semantics: the window is the half-open
 * interval [valid_from, valid_until) and a NULL bound means "open-ended in
 * that direction", so a multiplier with no bounds is always ACTIVE.
 */
export function deriveMultiplierStatus(
  multiplier: Pick<BonusMultiplier, "valid_from" | "valid_until">,
  now: Date,
): MultiplierStatus {
  if (multiplier.valid_from && now < new Date(multiplier.valid_from)) {
    return "SCHEDULED";
  }
  if (multiplier.valid_until && now >= new Date(multiplier.valid_until)) {
    return "EXPIRED";
  }
  return "ACTIVE";
}

/**
 * Describe what a multiplier applies to, resolving scope ids to names.
 *
 * NULL rule = every rule in the tenant; NULL segment = every user. When both
 * scopes are set the backend applies the INTERSECTION, so the label joins
 * them with "·".
 */
export function describeMultiplierScope(
  ruleName: string | null,
  segmentName: string | null,
): string {
  const rulePart = ruleName ? `Rule: ${ruleName}` : "All points rules";
  const segmentPart = segmentName ? `Segment: ${segmentName}` : "All users";
  return `${rulePart} · ${segmentPart}`;
}

/**
 * Render a multiplier's validity window as a short label.
 *
 * Open-ended bounds collapse to "From …" / "Until …", and a fully unbounded
 * window reads "Always active".
 */
export function formatMultiplierWindow(
  validFrom: string | null,
  validUntil: string | null,
): string {
  if (!validFrom && !validUntil) return "Always active";
  if (validFrom && !validUntil) return `From ${formatTimestamp(validFrom)}`;
  if (!validFrom && validUntil) return `Until ${formatTimestamp(validUntil)}`;
  return `${formatTimestamp(validFrom!)} → ${formatTimestamp(validUntil!)}`;
}

/**
 * Format the multiplication factor for display, e.g. "×2" or "×2.5".
 *
 * The API returns the factor as a decimal string ("2.00"); trailing zeros
 * are trimmed so the common integer factors read cleanly.
 */
export function formatMultiplierFactor(multiplier: string): string {
  const numeric = Number(multiplier);
  if (!Number.isFinite(numeric)) return `×${multiplier}`;
  return `×${String(numeric)}`;
}
