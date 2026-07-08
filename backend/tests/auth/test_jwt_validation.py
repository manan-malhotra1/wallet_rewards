"""Direct tests for the JWT verification chokepoint.

Covers every threat scenario from the Phase F.1 threat model §5.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import verify_jwt
from app.auth.tokens import extract_bearer_token
from app.shared.exceptions import (
    InvalidAlgorithm,
    InvalidAuthorizationHeader,
    InvalidToken,
    TokenExpired,
    UnknownSigningKey,
)

# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------


def test_extract_bearer_happy() -> None:
    """Standard Bearer header → token string."""
    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


def test_extract_bearer_missing_header() -> None:
    """None / empty → 401."""
    with pytest.raises(InvalidAuthorizationHeader):
        extract_bearer_token(None)


def test_extract_bearer_wrong_prefix() -> None:
    """Non-Bearer scheme → 401."""
    with pytest.raises(InvalidAuthorizationHeader):
        extract_bearer_token("Basic abc")


def test_extract_bearer_empty_token() -> None:
    """`Bearer ` with no token → 401."""
    with pytest.raises(InvalidAuthorizationHeader):
        extract_bearer_token("Bearer ")


def test_extract_bearer_case_insensitive_scheme() -> None:
    """`bearer` (lowercase) is accepted — HTTP scheme names are case-insensitive."""
    assert extract_bearer_token("bearer abc") == "abc"


# ---------------------------------------------------------------------------
# Verify happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_jwt_happy_path(
    make_admin_token: Callable[..., str],
) -> None:
    """Valid signed token → claims dict containing the expected fields."""
    token = make_admin_token(roles=["platform-admin"], username="alice-admin")
    claims = await verify_jwt(token)
    assert claims["preferred_username"] == "alice-admin"
    assert "platform-admin" in claims["realm_access"]["roles"]


# ---------------------------------------------------------------------------
# Signature / algorithm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_rejects_alg_none(
    make_admin_token: Callable[..., str],
) -> None:
    """`alg: none` is the classic attack — must be rejected."""
    # jose refuses to sign with 'none' via the normal encode path, so we
    # craft a token manually with the 'none' header.
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "kid": "test-key-1"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "realm_access": {"roles": ["platform-admin"]}}).encode()
    ).rstrip(b"=")
    forged = f"{header.decode()}.{payload.decode()}."

    with pytest.raises(InvalidAlgorithm):
        await verify_jwt(forged)


@pytest.mark.asyncio
async def test_verify_rejects_tampered_payload(
    private_key_pem: bytes,
    make_admin_token: Callable[..., str],
) -> None:
    """Tampering with the payload after signing breaks the signature."""
    token = make_admin_token(roles=["finance-reviewer"])
    header, payload, sig = token.split(".")
    # Flip a character in the payload — signature no longer matches.
    tampered_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    tampered = f"{header}.{tampered_payload}.{sig}"

    with pytest.raises(InvalidToken):
        await verify_jwt(tampered)


@pytest.mark.asyncio
async def test_verify_rejects_wrong_key_signature(
    make_admin_token: Callable[..., str],
) -> None:
    """A token signed by a key not in our JWKS → 401."""
    # Sign with a fresh key, label with our known kid — verification fails on signature.
    from jose import jwt as jose_jwt

    foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign_pem = foreign.private_bytes(
        encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.PEM,
        format=__import__("cryptography").hazmat.primitives.serialization.PrivateFormat.PKCS8,
        encryption_algorithm=__import__(
            "cryptography"
        ).hazmat.primitives.serialization.NoEncryption(),
    )
    forged = jose_jwt.encode(
        {
            "iss": "http://localhost:8080/realms/wallet-platform",
            "sub": "attacker",
            "exp": int(time.time()) + 60,
            "realm_access": {"roles": ["platform-admin"]},
        },
        foreign_pem,
        algorithm="RS256",
        headers={"kid": "test-key-1"},  # masquerade as the known kid
    )

    with pytest.raises(InvalidToken):
        await verify_jwt(forged)


@pytest.mark.asyncio
async def test_verify_rejects_unknown_kid(
    make_admin_token: Callable[..., str],
) -> None:
    """Token with a kid that's not in JWKS → 401 unknown_signing_key.

    Note: our verifier will try one refetch on miss. In tests the cache is
    seeded directly with one known kid, and no refetch can happen because we
    haven't enabled real HTTP — so an unknown kid stays unknown.
    """
    token = make_admin_token(roles=["platform-admin"], kid="never-issued")
    with pytest.raises(UnknownSigningKey):
        await verify_jwt(token)


# ---------------------------------------------------------------------------
# Expiry / issuer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_rejects_expired_token(
    make_admin_token: Callable[..., str],
) -> None:
    """exp in the past → TokenExpired (401)."""
    token = make_admin_token(roles=["platform-admin"], exp_seconds=-1)
    with pytest.raises(TokenExpired):
        await verify_jwt(token)


@pytest.mark.asyncio
async def test_verify_rejects_wrong_issuer(
    make_admin_token: Callable[..., str],
) -> None:
    """iss mismatch → InvalidToken (401)."""
    token = make_admin_token(
        roles=["platform-admin"],
        iss_override="http://attacker.example/realms/evil",
    )
    with pytest.raises(InvalidToken):
        await verify_jwt(token)
