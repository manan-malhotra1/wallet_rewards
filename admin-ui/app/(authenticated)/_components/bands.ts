/**
 * Shared multi-band helpers for the pricing + commission create dialogs
 * (Epic 25 / Task 8). A schedule is an ordered list of amount bands, each
 * carrying its own fixed + variable% + cap. The scope (service/currency/user
 * type) is common to every band and lives outside these rows.
 */

/** One editable band row. All values are raw strings from the form inputs. */
export interface BandRow {
  amount_from: string;
  amount_to: string;
  fixed: string;
  variable_pct: string;
  cap: string;
}

/** A fresh, empty band row. */
export function emptyBand(): BandRow {
  return { amount_from: "", amount_to: "", fixed: "0", variable_pct: "0", cap: "" };
}

/** Parse a band-bound string to a number, treating blank as unbounded (null). */
function bound(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/**
 * Validate a set of bands in input order. Returns an error message, or null
 * when the set is valid.
 *
 * Rules (mirrors the backend): at least one band; each bounded band's upper
 * bound exceeds its lower bound; bands are ascending and non-overlapping; only
 * the final band may be open-ended (blank upper bound).
 */
export function validateBands(bands: BandRow[]): string | null {
  if (bands.length === 0) return "Add at least one band.";
  for (let i = 0; i < bands.length; i++) {
    const from = bound(bands[i].amount_from);
    const to = bound(bands[i].amount_to);
    if (from !== null && to !== null && to <= from) {
      return `Band ${i + 1}: upper bound must be greater than the lower bound.`;
    }
    if (to === null && i < bands.length - 1) {
      return "Only the last band may be open-ended (blank upper bound).";
    }
    if (i > 0) {
      const prevTo = bound(bands[i - 1].amount_to);
      if (prevTo === null || from === null || from < prevTo) {
        return "Bands must be ascending and non-overlapping.";
      }
    }
  }
  return null;
}

/** Normalise a blank string to null; otherwise return the trimmed value. */
export function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}
