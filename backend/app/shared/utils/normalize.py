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

# Anything that isn't a digit or the leading '+' is whitespace / punctuation.
_PHONE_STRIP_RE = re.compile(r"[\s\-()\.]")


def normalize_phone(value: str) -> str:
    """Strip spaces / dashes / parens / dots; keep leading '+' + digits.

    Input examples that all map to `+27825550001`:
      - `+27 82 555 0001`
      - `+27-82-555-0001`
      - `+27 (82) 555.0001`
      - `+27825550001`

    Returns the original (unchanged) value if it's empty so the caller's
    validation layer can surface a "missing identifier" error rather than
    a silent normalisation.
    """
    if not value:
        return value
    return _PHONE_STRIP_RE.sub("", value).strip()


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
