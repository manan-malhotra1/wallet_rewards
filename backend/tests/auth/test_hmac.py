"""Unit tests for the HMAC verifier helper (Phase F.5).

These exercise the pure functions in `app.auth.hmac` — no DB, no FastAPI.
The E2E behaviour against the provider-callback endpoint is in
`tests/redemption/test_provider_callback.py`.
"""

from __future__ import annotations

import pytest

from app.auth.hmac import (
    REPLAY_WINDOW_SECONDS,
    build_signature_header,
    verify_signature,
)
from app.shared.exceptions import (
    InvalidSignature,
    SignatureMalformed,
    SignatureTimestampSkew,
)

SECRET = "a" * 64  # 64-char shared secret, comfortably above the 32-char minimum
BODY = b'{"outcome":"completed","external_reference":"MUKURU-1"}'


def test_signature_round_trip_succeeds():
    """A header built by `build_signature_header` verifies cleanly."""
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=1718473200)
    verify_signature(header=header, raw_body=BODY, secret=SECRET, now=1718473200)


def test_signature_inside_window_succeeds():
    """A header signed `REPLAY_WINDOW_SECONDS - 1` ago still verifies."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    verify_signature(
        header=header,
        raw_body=BODY,
        secret=SECRET,
        now=ts + REPLAY_WINDOW_SECONDS - 1,
    )


def test_signature_outside_window_raises_skew():
    """A header older than the replay window is rejected."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    with pytest.raises(SignatureTimestampSkew):
        verify_signature(
            header=header,
            raw_body=BODY,
            secret=SECRET,
            now=ts + REPLAY_WINDOW_SECONDS + 1,
        )


def test_signature_future_outside_window_raises_skew():
    """Timestamp from the future is also rejected (clock skew, not just stale)."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    with pytest.raises(SignatureTimestampSkew):
        verify_signature(
            header=header,
            raw_body=BODY,
            secret=SECRET,
            now=ts - REPLAY_WINDOW_SECONDS - 1,
        )


def test_tampered_body_raises_invalid_signature():
    """Mutating a single byte of the body invalidates the signature."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    tampered = BODY.replace(b"MUKURU-1", b"MUKURU-2")
    with pytest.raises(InvalidSignature):
        verify_signature(header=header, raw_body=tampered, secret=SECRET, now=ts)


def test_wrong_secret_raises_invalid_signature():
    """Verifying with a different secret fails."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    with pytest.raises(InvalidSignature):
        verify_signature(header=header, raw_body=BODY, secret="b" * 64, now=ts)


def test_missing_v1_raises_malformed():
    """Header without a `v1=` field is malformed."""
    with pytest.raises(SignatureMalformed):
        verify_signature(header="t=1718473200", raw_body=BODY, secret=SECRET, now=1718473200)


def test_missing_timestamp_raises_malformed():
    """Header without a `t=` field is malformed."""
    with pytest.raises(SignatureMalformed):
        verify_signature(header="v1=deadbeef", raw_body=BODY, secret=SECRET, now=1718473200)


def test_non_integer_timestamp_raises_malformed():
    """`t=` must be an integer; anything else is malformed."""
    with pytest.raises(SignatureMalformed):
        verify_signature(
            header="t=notanumber,v1=deadbeef",
            raw_body=BODY,
            secret=SECRET,
            now=1718473200,
        )


def test_multiple_v1_digests_verify_when_any_matches():
    """Rotation case — multiple `v1=` values; verify passes if ANY matches."""
    ts = 1718473200
    good_header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    # Inject an extra (wrong) digest before the good one; both should be tried.
    parts = good_header.split(",")
    timestamp_part = parts[0]
    good_v1 = parts[1]
    composed = f"{timestamp_part},v1=0000000000000000,{good_v1}"
    verify_signature(header=composed, raw_body=BODY, secret=SECRET, now=ts)


def test_uppercase_v1_is_compared_case_insensitively():
    """Hex digests are lowercased before constant-time compare."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    upper_header = header.replace("v1=", "v1=").upper().replace("T=", "t=").replace("V1=", "v1=")
    verify_signature(header=upper_header, raw_body=BODY, secret=SECRET, now=ts)


def test_extra_unknown_fields_ignored():
    """Forwards-compat — unknown header fields don't break verification."""
    ts = 1718473200
    header = build_signature_header(raw_body=BODY, secret=SECRET, timestamp=ts)
    composed = f"{header},v2=futurefield,extra=value"
    verify_signature(header=composed, raw_body=BODY, secret=SECRET, now=ts)
