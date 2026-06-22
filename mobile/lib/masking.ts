/**
 * PII masking helpers — phones only (for now).
 *
 * Per .claude/rules/compliance-fintech.md, any phone shown back to the
 * user in error / status messages should be masked: middle digits become
 * asterisks. The canonical input is E.164 (`+27...`).
 */

/**
 * Mask an E.164 phone for display:
 *   `+27825550142` → `+27 82 *** 0142`
 * Falls back to the original input if it's too short to mask sensibly.
 */
export function maskPhone(e164: string): string {
  const digits = e164.replace(/\D/g, '');
  if (digits.length < 9) return e164;
  // Pull the trailing 4 (last group) and the next 2 (first national group).
  const tail = digits.slice(-4);
  // Country code = everything before the national. We don't have a parser;
  // assume 1–3 digit country code based on common diaspora corridors. Take
  // the first 1–3 digits up to a known list.
  const knownDial = ['1', '27', '44', '91', '263'];
  let dial = digits.slice(0, 3);
  if (knownDial.includes(digits.slice(0, 1))) dial = digits.slice(0, 1);
  else if (knownDial.includes(digits.slice(0, 2))) dial = digits.slice(0, 2);
  else if (knownDial.includes(digits.slice(0, 3))) dial = digits.slice(0, 3);
  const rest = digits.slice(dial.length);
  const first = rest.slice(0, 2);
  return `+${dial} ${first} *** ${tail}`;
}
