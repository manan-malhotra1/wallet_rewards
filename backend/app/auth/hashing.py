"""bcrypt wrappers for PIN and OTP — single chokepoint.

NEVER pass plaintext PIN/OTP outside this module.
Per NFR-0170 / `.claude/rules/compliance-fintech.md`:
  - PIN, OTP, session tokens NEVER appear in logs, audit, API responses, or DB
    fields in plain form
  - bcrypt cost ≥ 12

Uses the `bcrypt` library directly (not passlib) — passlib's API check is
broken with bcrypt 4.x. bcrypt 4.x is the actively-maintained library.

Why bcrypt for OTP (a 6-digit code with limited entropy)? Two reasons:
  1. Defence in depth — even if `otp_requests` leaks, OTPs aren't readable.
  2. Consistency — same primitive as PIN, easy to reason about.
"""
from __future__ import annotations

import secrets

import bcrypt

# Cost 12 — common balance between security and latency on commodity hardware.
# One verify is ~150ms; brute-forcer doing 10^6 guesses pays ~50 CPU-hours per
# account against a single 6-digit OTP.
_BCRYPT_ROUNDS = 12


def hash_pin(pin: str) -> str:
    """One-way hash a PIN. Returned string is what gets stored in users.pin_hash."""
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Constant-time PIN comparison. Returns False on any error."""
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_otp(otp: str) -> str:
    """One-way hash an OTP for storage in otp_requests.otp_hash."""
    return bcrypt.hashpw(otp.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("utf-8")


def verify_otp(otp: str, otp_hash: str) -> bool:
    """Constant-time OTP comparison. Returns False on any error."""
    try:
        return bcrypt.checkpw(otp.encode("utf-8"), otp_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_otp() -> str:
    """Generate a fresh 6-digit OTP using a cryptographic RNG.

    Returned as a string with leading zeros preserved (e.g. "004721"). Tests
    monkey-patch this function to get deterministic OTPs.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_token() -> str:
    """Cryptographically random opaque token for sessions / registration tokens.

    32 bytes → 256 bits of entropy → URL-safe base64. Collision-resistant for
    any plausible scale.
    """
    return secrets.token_urlsafe(32)
