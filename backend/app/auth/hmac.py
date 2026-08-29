"""HMAC-SHA256 signature verification for third-party callbacks (Phase F.5).

Used by:
- `POST /airtime/{id}/callback` to verify the merchant's signature against
  `merchant_profiles.callback_secret_encrypted` (decrypted at request time).
- Kafka consumer of `wallet.events.external` to verify the producer's
  signature against `external_event_sources.shared_secret_encrypted`
  (decrypted at request time).

Wire format (matches the Phase F.5 threat model):

    X-Sasai-Signature: t=<unix_seconds>,v1=<hex_hmac_sha256>

    canonical_string = "{t}.{raw_body_utf8}"
    signature        = hex(HMAC_SHA256(shared_secret, canonical_string))

Replay window: ≤ 300 seconds (NFR-0210). Constant-time compare with
`hmac.compare_digest`. Multiple `v1=` values in a single header value are
supported during secret rotation — verification passes if any match.

This module is intentionally pure (no DB, no network) so it can be unit
tested in isolation. Callers pass the lookup result (shared_secret string).
"""

from __future__ import annotations

import hmac
import time
from hashlib import sha256

from app.shared.exceptions import (
    InvalidSignature,
    SignatureMalformed,
    SignatureTimestampSkew,
)

# Maximum tolerable clock skew between the signing party and us, both sides.
# 5 minutes per NFR-0210 / the F.5 threat model.
REPLAY_WINDOW_SECONDS = 300


def _parse_signature_header(header: str) -> tuple[int, list[str]]:
    """Pull the timestamp and one-or-more v1 digests out of the header.

    Expected form: ``t=1718473200,v1=abc...,v1=def...``. The order of
    fields doesn't matter; extra unknown fields are ignored (forwards-compat).

    Raises:
        SignatureMalformed: header missing `t=` or any `v1=` token.
    """
    timestamp: int | None = None
    digests: list[str] = []
    for part in header.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise SignatureMalformed("Signature timestamp is not an integer.") from exc
        elif key == "v1":
            digests.append(value)
    if timestamp is None or not digests:
        raise SignatureMalformed("Signature header must contain `t=` and at least one `v1=`.")
    return timestamp, digests


def _compute_expected(timestamp: int, raw_body: bytes, secret: str) -> str:
    """Hex digest of HMAC-SHA256 over `{timestamp}.{body}` with `secret`.

    Always returns lowercase hex (matches `hmac.compare_digest` semantics
    used by `verify_signature`).
    """
    canonical = f"{timestamp}.".encode() + raw_body
    return hmac.new(secret.encode("utf-8"), canonical, sha256).hexdigest()


def verify_signature(
    *,
    header: str,
    raw_body: bytes,
    secret: str,
    now: int | None = None,
) -> None:
    """Verify an X-Sasai-Signature header against a body + shared secret.

    Returns silently on success. Raises the appropriate 401 exception
    otherwise — the FastAPI exception handler maps it to the JSON response.

    Args:
        header: Raw value of the `X-Sasai-Signature` request header.
        raw_body: The exact request body bytes — read BEFORE Pydantic
            parsing or any whitespace-normalising step.
        secret: The verifier's shared secret — the decrypted plaintext of
            `provider.shared_secret_encrypted` or
            `source.shared_secret_encrypted`.
        now: Override for tests. Defaults to `time.time()` (UTC seconds).

    Raises:
        SignatureMalformed: header missing required fields.
        SignatureTimestampSkew: |now - t| > REPLAY_WINDOW_SECONDS.
        InvalidSignature: no `v1=` digest matched the expected HMAC.
    """
    timestamp, digests = _parse_signature_header(header)

    current = int(now if now is not None else time.time())
    if abs(current - timestamp) > REPLAY_WINDOW_SECONDS:
        raise SignatureTimestampSkew()

    expected = _compute_expected(timestamp, raw_body, secret)
    # Constant-time compare against EACH provided digest. Iteration is
    # bounded by len(digests) which is tiny (≤ 2 during rotation).
    for candidate in digests:
        if hmac.compare_digest(expected, candidate.lower()):
            return
    raise InvalidSignature()


def build_signature_header(*, raw_body: bytes, secret: str, timestamp: int | None = None) -> str:
    """Construct an X-Sasai-Signature value (used by tests + signing clients).

    The platform itself never signs callbacks — third parties do that. This
    helper exists for the test suite and any internal tooling that signs
    payloads to feed into the verifier.

    Args:
        raw_body: Exact bytes that will go on the wire.
        secret: Same secret the verifier will use.
        timestamp: Defaults to `int(time.time())`.

    Returns:
        Header value of the form `t=<int>,v1=<hex>`.
    """
    ts = int(timestamp if timestamp is not None else time.time())
    digest = _compute_expected(ts, raw_body, secret)
    return f"t={ts},v1={digest}"
