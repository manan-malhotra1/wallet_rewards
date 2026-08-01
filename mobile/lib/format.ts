/**
 * Tiny formatters for currency, points, and phone masking.
 *
 * Kept dependency-free (no Intl.NumberFormat polyfills) so the bundle stays
 * small on Hermes. The app is multi-currency — always format via
 * `formatMoney(amount, currency)`, never assume ZAR.
 */

/** Display symbol per currency code. Falls back to the code + a space. */
const CURRENCY_SYMBOL: Record<string, string> = {
  ZAR: 'R',
  INR: '₹',
  USD: '$',
  GBP: '£',
  EUR: '€',
};

/**
 * Return the display symbol for a currency code (e.g. "R", "₹").
 * Unknown codes fall back to the code itself with a trailing space
 * (e.g. "TOKEN 1,200.00") so an unmapped currency is never mis-labelled.
 */
export function currencySymbol(currency: string): string {
  return CURRENCY_SYMBOL[currency] ?? `${currency} `;
}

/**
 * Format a Decimal-string amount for a given currency, e.g.
 * `formatMoney("12450", "ZAR")` → "R 12,450.00", `("999", "INR")` → "₹ 999.00".
 */
export function formatMoney(amount: string | number, currency: string): string {
  const n = typeof amount === 'string' ? parseFloat(amount) : amount;
  const sym = currencySymbol(currency);
  if (!Number.isFinite(n)) return `${sym}0.00`;
  const parts = n.toFixed(2).split('.');
  // Insert thousands separators into the integer part.
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sym}${parts.join('.')}`;
}

/** Back-compat ZAR formatter — delegates to `formatMoney`. Prefer `formatMoney`. */
export function formatZAR(amount: string | number): string {
  return formatMoney(amount, 'ZAR');
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
