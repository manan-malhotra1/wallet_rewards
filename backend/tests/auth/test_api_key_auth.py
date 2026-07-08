"""Tests for the API-key + HMAC request verification (Epic 14 S3).

`verify_api_key_request` is the core of the external-API auth path: resolve
the active key from its public key_id, recover the secret, verify the HMAC
signature over the raw body, and hand back a tenant-scoped principal.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import ApiKeyPrincipal, verify_api_key_request
from app.auth.secret_box import encrypt_secret
from app.shared.exceptions import (
    ApiKeyInvalid,
    InvalidSignature,
    SignatureMalformed,
    SignatureTimestampSkew,
)
from app.shared.models import ApiKey, Tenant

_SECRET = "sak_secret_value_do_not_log"
_BODY = b'{"identifiers":[{"identifier_type":"email","identifier_value":"a@b.co"}]}'
_TS = 1_800_000_000  # fixed clock for deterministic signatures


def _sign(secret: str, raw_body: bytes, ts: int) -> str:
    """Build a valid X-Sasai-Signature header the way a partner would."""
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


async def _make_key(
    session: AsyncSession, tenant: Tenant, *, key_id: str = "sak_live_abc", status: str = "active"
) -> ApiKey:
    key = ApiKey(
        tenant_id=tenant.id,
        key_id=key_id,
        secret_encrypted=encrypt_secret(_SECRET),
        status=status,
    )
    session.add(key)
    await session.commit()
    return key


@pytest.mark.asyncio
async def test_valid_signature_returns_tenant_principal(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A correctly-signed request resolves to the key's tenant and stamps
    last_used_at."""
    await _make_key(db_session, test_tenant, key_id="sak_live_ok")
    principal = await verify_api_key_request(
        db_session,
        key_id="sak_live_ok",
        signature_header=_sign(_SECRET, _BODY, _TS),
        raw_body=_BODY,
        now=_TS,
    )
    assert isinstance(principal, ApiKeyPrincipal)
    assert principal.tenant_id == test_tenant.id
    assert principal.key_id == "sak_live_ok"

    await db_session.commit()
    row = (
        await db_session.execute(select(ApiKey).where(ApiKey.key_id == "sak_live_ok"))
    ).scalar_one()
    assert row.last_used_at is not None


@pytest.mark.asyncio
async def test_unknown_key_id_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """A key_id that doesn't exist is rejected (no existence leak)."""
    with pytest.raises(ApiKeyInvalid):
        await verify_api_key_request(
            db_session,
            key_id="sak_live_nope",
            signature_header=_sign(_SECRET, _BODY, _TS),
            raw_body=_BODY,
            now=_TS,
        )


@pytest.mark.asyncio
async def test_revoked_key_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """A revoked key does not authenticate, even with a valid signature."""
    await _make_key(db_session, test_tenant, key_id="sak_live_revoked", status="revoked")
    with pytest.raises(ApiKeyInvalid):
        await verify_api_key_request(
            db_session,
            key_id="sak_live_revoked",
            signature_header=_sign(_SECRET, _BODY, _TS),
            raw_body=_BODY,
            now=_TS,
        )


@pytest.mark.asyncio
async def test_tampered_body_rejected(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """A signature computed over a different body fails verification."""
    await _make_key(db_session, test_tenant, key_id="sak_live_tamper")
    with pytest.raises(InvalidSignature):
        await verify_api_key_request(
            db_session,
            key_id="sak_live_tamper",
            signature_header=_sign(_SECRET, b'{"different":"body"}', _TS),
            raw_body=_BODY,
            now=_TS,
        )


@pytest.mark.asyncio
async def test_timestamp_outside_window_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A signature older than the 300s replay window is rejected."""
    await _make_key(db_session, test_tenant, key_id="sak_live_stale")
    with pytest.raises(SignatureTimestampSkew):
        await verify_api_key_request(
            db_session,
            key_id="sak_live_stale",
            signature_header=_sign(_SECRET, _BODY, _TS),
            raw_body=_BODY,
            now=_TS + 400,  # 400s later — outside the window
        )


@pytest.mark.asyncio
async def test_malformed_signature_header_rejected(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A signature header missing t=/v1= is rejected as malformed."""
    await _make_key(db_session, test_tenant, key_id="sak_live_bad_hdr")
    with pytest.raises(SignatureMalformed):
        await verify_api_key_request(
            db_session,
            key_id="sak_live_bad_hdr",
            signature_header="not-a-real-signature",
            raw_body=_BODY,
            now=_TS,
        )
