/**
 * PII masking for anything the admin UI hands back to the browser.
 *
 * NFR-0240 requires identifiers to be masked outside the surfaces that
 * genuinely need them. The backend's `shared/utils/masking.py` is the canonical
 * implementation; these mirror it digit-for-digit so a value masked on either
 * side of the wire reads the same.
 *
 * Use these in server actions, before a resolved person's details cross into a
 * client component — never mask in the browser, because by then the unmasked
 * value has already been shipped.
 */

/**
 * Mask the middle digits of a phone number, keeping the first and last four.
 *
 * Mirrors `mask_phone` in `backend/app/shared/utils/masking.py`.
 *
 * @param phone - Phone number in any format, with or without separators.
 * @returns The masked number, or `"***"` when it is too short to mask safely.
 */
export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 8) return "***";
  return `+${digits.slice(0, 4)} *** ${digits.slice(-4)}`;
}
