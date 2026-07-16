"""Integration tests for POST /api/v1/external/users (Epic 14 S4).

The external partner API: HMAC-signed, tenant derived from the API key,
reuses identity.create_user, idempotent on retry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.secret_box import encrypt_secret
from app.shared.models import ApiKey, AuditLog, Tenant, User, UserIdentifier

_SECRET = "ext-partner-secret-do-not-log"


@pytest_asyncio.fixture
async def api_key(db_session: AsyncSession, test_tenant: Tenant) -> AsyncIterator[dict[str, str]]:
    """An active API key for the test tenant, with a known plaintext secret."""
    db_session.add(
        ApiKey(
            tenant_id=test_tenant.id,
            key_id="sak_live_ext",
            secret_encrypted=encrypt_secret(_SECRET),
        )
    )
    await db_session.commit()
    yield {"key_id": "sak_live_ext", "secret": _SECRET}


def _sign_headers(
    key_id: str, secret: str, raw: bytes, *, idem: str = "idem-key-1"
) -> dict[str, str]:
    """Build the header set a partner would send for a signed request."""
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return {
        "X-Sasai-Api-Key": key_id,
        "X-Sasai-Signature": f"t={ts},v1={digest}",
        "Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


def _body(email: str = "partner.user@example.com") -> dict:
    return {"identifiers": [{"identifier_type": "email", "identifier_value": email}]}


@pytest.mark.asyncio
async def test_valid_request_creates_user_in_key_tenant(
    async_client: AsyncClient, test_tenant: Tenant, api_key: dict[str, str]
) -> None:
    """A correctly-signed request creates a consumer in the KEY's tenant."""
    raw = json.dumps(_body()).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["tenant_id"] == str(test_tenant.id)  # tenant from key, not body
    assert data["user_type"] == "consumer"
    assert data["identifiers"][0]["identifier_value"] == "partner.user@example.com"


@pytest.mark.asyncio
async def test_valid_request_writes_system_actor_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """The partner path has no admin — the created user is audited as a
    system actor keyed on the API key (NFR-0160 / NFR-0250)."""
    raw = json.dumps(_body("audited.partner@example.com")).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "user",
                    AuditLog.entity_id == user_id,
                    AuditLog.action == "user.created",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "system"
    assert row.actor_id == f"apikey:{api_key['key_id']}"
    assert row.tenant_id == test_tenant.id
    assert row.after_state["identifier_count"] == 1


@pytest.mark.asyncio
async def test_idempotent_replay_writes_no_second_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """An idempotent replay (existing identifier) must not double-audit."""
    raw = json.dumps(_body("dupaudit@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert first.status_code == 201, first.text
    user_id = first.json()["id"]

    raw2 = json.dumps(_body("dupaudit@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="idem-key-2"),
    )
    assert second.status_code == 200, second.text

    count = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.entity_id == user_id, AuditLog.action == "user.created")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_missing_auth_headers_rejected(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """No API key / signature -> 401 api_key_invalid."""
    raw = json.dumps(_body()).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers={"Idempotency-Key": "x", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "api_key_invalid"


@pytest.mark.asyncio
async def test_bad_signature_rejected(async_client: AsyncClient, api_key: dict[str, str]) -> None:
    """A signature computed with the wrong secret -> 401 invalid_signature."""
    raw = json.dumps(_body()).encode()
    headers = _sign_headers(api_key["key_id"], "the-wrong-secret", raw)
    resp = await async_client.post("/api/v1/external/users", content=raw, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """The Idempotency-Key header is required (Pay-PRD-0200)."""
    raw = json.dumps(_body()).encode()
    headers = _sign_headers(api_key["key_id"], api_key["secret"], raw)
    del headers["Idempotency-Key"]
    resp = await async_client.post("/api/v1/external/users", content=raw, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_email_or_phone_rejected(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """A partner-created user must be contactable by email or phone."""
    body = {"identifiers": [{"identifier_type": "account_number", "identifier_value": "ZA-1"}]}
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Re-sending the same create (same identifier) returns the existing user
    rather than a 409 — retries are safe, and only one user is created."""
    raw = json.dumps(_body("dup@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert first.status_code == 201, first.text

    raw2 = json.dumps(_body("dup@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="idem-key-2"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == test_tenant.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_rate_limit_returns_429(
    async_client: AsyncClient, api_key: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once a key exceeds its per-window quota, further requests get 429."""
    import app.auth.rate_limit as rl

    monkeypatch.setattr(rl, "API_KEY_RATE_LIMIT", 1)
    raw1 = json.dumps(_body("rl1@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw1,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw1),
    )
    assert first.status_code == 201, first.text

    raw2 = json.dumps(_body("rl2@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="idem-key-2"),
    )
    assert second.status_code == 429
    assert second.json()["error_code"] == "rate_limited"


@pytest.mark.asyncio
async def test_partner_cannot_mass_assign_privileged_fields(
    async_client: AsyncClient,
    db_session: AsyncSession,
    api_key: dict[str, str],
) -> None:
    """A partner cannot set user_type / verified / parent_user_id (S7 H1);
    they are forced server-side to consumer / False / none."""
    body = {
        "identifiers": [
            {
                "identifier_type": "email",
                "identifier_value": "escalate@example.com",
                "verified": True,
            }
        ],
        "user_type": "head_merchant",
        "parent_user_id": str(uuid4()),
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["user_type"] == "consumer"  # not head_merchant
    assert data["parent_user_id"] is None  # not the supplied uuid
    row = (
        await db_session.execute(
            select(UserIdentifier).where(UserIdentifier.identifier_value == "escalate@example.com")
        )
    ).scalar_one()
    assert row.verified is False  # partner-supplied verified=True was ignored
