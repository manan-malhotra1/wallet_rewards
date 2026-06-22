/**
 * Tiny formatters for currency, points, and phone masking.
 *
 * Kept dependency-free (no Intl.NumberFormat polyfills) so the bundle stays
 * small on Hermes. ZAR is the only currency in the app right now; if we
 * grow multi-currency, switch to Intl.NumberFormat with locale="en-ZA".
 */

/** Format a Decimal-string amount as "R 12,450.00". */
export function formatZAR(amount: string | number): string {
  const n = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (!Number.isFinite(n)) return 'R 0.00';
  const parts = n.toFixed(2).split('.');
  // Insert thousands separators into the integer part.
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `R ${parts.join('.')}`;
}

/** Format an integer PTS amount as "340 PTS". */
export function formatPTS(points: number | string): string {
  const n = typeof points === 'string' ? parseInt(points, 10) : Math.trunc(points);
  return `${(Number.isFinite(n) ? n : 0).toLocaleString('en-ZA')} PTS`;
}

/**
 * Mask an E.164 phone for display: "+27821112233" → "+27 82 *** 2233".
 *
 * Per .claude/rules/compliance-fintech.md: PII must be masked in UI logs and
 * non-essential displays. This helper is for showing a phone back to the
 * user where the full number isn't needed.
 */
export function maskPhone(e164: string): string {
  if (!e164.startsWith('+') || e164.length < 8) return e164;
  // Drop the leading + and split country/national portions.
  const digits = e164.slice(1);
  const cc = digits.slice(0, 2); // assume 2-digit country code; good enough for ZA/IN/UK/US/ZW
  const nat = digits.slice(2);
  if (nat.length < 6) return e164; // too short to mask meaningfully
  const lead = nat.slice(0, 2);
  const tail = nat.slice(-4);
  return `+${cc} ${lead} *** ${tail}`;
}
