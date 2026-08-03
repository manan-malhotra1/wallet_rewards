"""Identifier normalisation helpers.

Every identifier that's stored, indexed, or used for lookup goes through
one of these so the canonical form is consistent everywhere. Spaces,
dashes, parentheses are all visual sugar — they should NOT be persisted.

Run normalisation at:
  - write time (CreateUserRequest.identifier_value)
  - lookup time (resolve_identifier path/body params)
  - import time (admin user-uploads, future)

Without this, "+27 82 555 0001" and "+27825550001" are different rows and
lookups silently miss. NFR-0220 (tenant isolation) is also weakened
because near-duplicates can slip into different tenants.
"""

from __future__ import annotations

import re

# Everything that isn't a digit is stripped; a single leading '+' is then
# re-applied so the canonical form is ALWAYS E.164 (`+` + digits only).
_NON_DIGIT_RE = re.compile(r"\D")


def normalize_phone(value: str) -> str:
    """Canonicalise a phone to E.164 form: a single leading '+' then digits.

    Strips EVERY non-digit character (spaces, dashes, parens, dots, and any
    stray '+' — including a missing or duplicated one) and re-prepends exactly
    one '+'. This makes the presence/absence of the leading '+' irrelevant so
    the SAME real number resolves to ONE identifier everywhere (uniqueness at
    create_user / add_identifier / the maker-checker propose-revise duplicate
    guard, and auth/OTP lookup). Matches the stored convention — every existing
    `user_identifiers` phone value is already `+`-prefixed digits.

    Input examples that all map to `+27825550001`:
      - `27825550001`      (no leading '+')
      - `+27825550001`
      - `+27 82 555 0001`
      - `+27-82-555-0001`
      - `+27 (82) 555.0001`

    Returns the original (unchanged) value if it's empty so the caller's
    validation layer can surface a "missing identifier" error rather than
    a silent normalisation.
    """
    if not value:
        return value
    digits = _NON_DIGIT_RE.sub("", value)
    # An all-punctuation input strips to empty; leave it empty (no bare '+')
    # so validation still rejects it rather than minting a '+' identifier.
    if not digits:
        return ""
    return f"+{digits}"


def normalize_identifier(identifier_type: str, value: str) -> str:
    """Apply the right normaliser based on `identifier_type`.

    Phone gets stripped to digits + leading `+`. Email is lowercased
    (case-insensitivity matches industry convention — `Jane@x.com` and
    `jane@x.com` point to the same person). Account and card identifiers
    are passed through unchanged for now; they tend to carry meaningful
    grouping characters (e.g. `ZA-001-887-2210`).
    """
    if identifier_type == "phone":
        return normalize_phone(value)
    if identifier_type == "email":
        return value.strip().lower()
    return value.strip()
