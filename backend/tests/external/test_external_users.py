"""Partner-created customer accounts.

The external partner API: HMAC-signed, tenant derived from the API key,
reuses identity.create_user, idempotent on retry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.secret_box import encrypt_secret
from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.modules.user_types.schemas import UserTypeCreateRequest
from app.modules.user_types.service import create_user_type
from app.shared.models import (
    ApiKey,
    AuditLog,
    ExternalUserCreation,
    Role,
    Tenant,
    User,
    UserIdentifier,
)

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
    """Verify a partner can create a customer in its own tenant"""
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
    """Verify a partner-created customer is recorded in the audit trail"""
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
    """Verify retrying a customer creation does not record a second audit entry"""
    raw = json.dumps(_body("dupaudit@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="retry-key"),
    )
    assert first.status_code == 201, first.text
    user_id = first.json()["id"]

    raw2 = json.dumps(_body("dupaudit@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="retry-key"),
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
    """Verify an unsigned customer-creation request is rejected"""
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
    """Verify a customer-creation request with an invalid signature is rejected"""
    raw = json.dumps(_body()).encode()
    headers = _sign_headers(api_key["key_id"], "the-wrong-secret", raw)
    resp = await async_client.post("/api/v1/external/users", content=raw, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_signature"


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """Verify a customer-creation request without an idempotency key is rejected"""
    raw = json.dumps(_body()).encode()
    headers = _sign_headers(api_key["key_id"], api_key["secret"], raw)
    del headers["Idempotency-Key"]
    resp = await async_client.post("/api/v1/external/users", content=raw, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_email_or_phone_rejected(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """Verify a partner-created customer must have an email or phone"""
    body = {"identifiers": [{"identifier_type": "account_number", "identifier_value": "ZA-1"}]}
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_same_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify retrying a customer creation returns the same customer, not a second one"""
    raw = json.dumps(_body("retry@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="same-key"),
    )
    assert first.status_code == 201, first.text

    raw2 = json.dumps(_body("retry@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="same-key"),
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == test_tenant.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_new_key_free_identifier_writes_idempotency_row(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify a newly created customer is recorded so a later retry can replay it"""
    raw = json.dumps(_body("recorded@example.com")).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="record-key"),
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    row = (
        await db_session.execute(
            select(ExternalUserCreation).where(
                ExternalUserCreation.tenant_id == test_tenant.id,
                ExternalUserCreation.idempotency_key == "record-key",
            )
        )
    ).scalar_one()
    assert str(row.user_id) == user_id


@pytest.mark.asyncio
async def test_new_key_taken_identifier_returns_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify creating a customer with an already-used contact detail is rejected as a conflict"""
    raw = json.dumps(_body("conflict@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="key-a"),
    )
    assert first.status_code == 201, first.text

    raw2 = json.dumps(_body("conflict@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw2, idem="key-b"),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "identifier_already_in_use"

    # Still exactly one user — the conflict created nothing.
    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == test_tenant.id)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_store_insert_conflict_replays_winner(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify two simultaneous retries create a single customer.

    True concurrency is impractical against the shared test DB, so we force the
    INSERT-collision branch: pre-seed the winner's mapping and make the initial
    idempotency lookup miss once (the race window between fast-path and INSERT).
    """
    # Seed the "winner": an already-created user + its recorded mapping.
    winner_raw = json.dumps(_body("winner@example.com")).encode()
    winner = await async_client.post(
        "/api/v1/external/users",
        content=winner_raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], winner_raw, idem="winner-key"),
    )
    assert winner.status_code == 201, winner.text
    winner_id = winner.json()["id"]

    db_session.add(
        ExternalUserCreation(
            tenant_id=test_tenant.id,
            idempotency_key="race-key",
            user_id=winner_id,
        )
    )
    await db_session.commit()

    # Force the fast-path lookup to miss exactly once, so the loser proceeds to
    # create + INSERT and collides with the seeded mapping.
    import app.modules.external.service as ext_service

    real_lookup = ext_service._find_external_creation
    calls = {"n": 0}

    async def _miss_once(session: AsyncSession, tenant_id: object, key: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(session, tenant_id, key)  # type: ignore[arg-type]

    monkeypatch.setattr(ext_service, "_find_external_creation", _miss_once)

    raw = json.dumps(_body("loser@example.com")).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="race-key"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == winner_id  # replayed the winner, not the loser


@pytest.mark.asyncio
async def test_same_key_two_tenants_creates_independently(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify the same idempotency key in two tenants creates two separate customers"""
    other_secret = "ext-partner-secret-other"
    db_session.add(
        ApiKey(
            tenant_id=other_tenant.id,
            key_id="sak_live_other",
            secret_encrypted=encrypt_secret(other_secret),
        )
    )
    await db_session.commit()

    raw = json.dumps(_body("shared@example.com")).encode()
    first = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="cross-tenant-key"),
    )
    assert first.status_code == 201, first.text
    assert first.json()["tenant_id"] == str(test_tenant.id)

    raw2 = json.dumps(_body("shared@example.com")).encode()
    second = await async_client.post(
        "/api/v1/external/users",
        content=raw2,
        headers=_sign_headers("sak_live_other", other_secret, raw2, idem="cross-tenant-key"),
    )
    assert second.status_code == 201, second.text
    assert second.json()["tenant_id"] == str(other_tenant.id)
    assert second.json()["id"] != first.json()["id"]


@pytest.mark.asyncio
async def test_rate_limit_returns_429(
    async_client: AsyncClient, api_key: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a partner exceeding its request quota is throttled"""
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
    """Verify a partner cannot set privileged fields when creating a customer

    `user_type` became a legitimate field with the user-types catalog (spec
    §7.3) and has its own tests below. The two fields here stayed privileged:
    a raw `parent_user_id` would let a partner graft the hierarchy without a
    tenant-scoped lookup, and `verified` would let it assert contact details
    the platform never confirmed.
    """
    body = {
        "identifiers": [
            {
                "identifier_type": "email",
                "identifier_value": "escalate@example.com",
                "verified": True,
            }
        ],
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
    assert data["parent_user_id"] is None  # not the supplied uuid
    row = (
        await db_session.execute(
            select(UserIdentifier).where(UserIdentifier.identifier_value == "escalate@example.com")
        )
    ).scalar_one()
    assert row.verified is False  # partner-supplied verified=True was ignored


@pytest.mark.asyncio
async def test_partner_onboards_an_agent_with_a_supervisor(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify the partner API can create a non-consumer and attach a supervisor"""
    boss_body = {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825556000"}],
        "user_type": "super_agent",
    }
    raw = json.dumps(boss_body).encode()
    boss = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-boss"),
    )
    assert boss.status_code == 201, boss.text

    agent_body = {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825556001"}],
        "user_type": "agent",
        "parent_identifier": {"identifier_type": "phone", "identifier_value": "+27825556000"},
    }
    raw = json.dumps(agent_body).encode()
    agent = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-agent"),
    )
    assert agent.status_code == 201, agent.text

    created = (
        await db_session.execute(select(User).where(User.id == UUID(agent.json()["id"])))
    ).scalar_one()
    assert created.tenant_id == test_tenant.id
    assert created.user_type == "agent"
    assert created.parent_user_id == UUID(boss.json()["id"])


@pytest.mark.asyncio
async def test_partner_cannot_use_an_unknown_type(
    async_client: AsyncClient, api_key: dict[str, str]
) -> None:
    """Verify widening the endpoint did not make it trust the body"""
    body = {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825557000"}],
        "user_type": "not_a_real_type",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-badtype"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"


@pytest.mark.asyncio
async def test_partner_cannot_use_another_tenants_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    other_tenant: Tenant,
    api_key: dict[str, str],
) -> None:
    """Verify the type is resolved against the KEY's tenant, not the whole platform"""
    await create_user_type(
        db_session,
        UserTypeCreateRequest(
            tenant_id=other_tenant.id,
            code="franchisee",
            label="Franchisee",
            category_code="retail",
        ),
    )
    body = {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825557100"}],
        "user_type": "franchisee",
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-xtenant"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "unknown_user_type"


@pytest.mark.asyncio
async def test_partner_supervisor_lookup_is_tenant_scoped(
    async_client: AsyncClient,
    db_session: AsyncSession,
    other_tenant: Tenant,
    default_user_role_other_tenant: Role,
    api_key: dict[str, str],
) -> None:
    """Verify a supervisor in another tenant looks identical to a missing one"""
    await create_user(
        db_session,
        CreateUserRequest(
            tenant_id=other_tenant.id,
            identifiers=[IdentifierIn(identifier_type="phone", identifier_value="+27825557200")],
            user_type="super_agent",
        ),
    )
    body = {
        "identifiers": [{"identifier_type": "phone", "identifier_value": "+27825557201"}],
        "user_type": "agent",
        "parent_identifier": {"identifier_type": "phone", "identifier_value": "+27825557200"},
    }
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-xparent"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "parent_not_found"


@pytest.mark.asyncio
async def test_partner_still_defaults_to_consumer(
    async_client: AsyncClient, db_session: AsyncSession, api_key: dict[str, str]
) -> None:
    """Verify omitting user_type keeps the old behaviour for existing partners"""
    body = {"identifiers": [{"identifier_type": "phone", "identifier_value": "+27825558000"}]}
    raw = json.dumps(body).encode()
    resp = await async_client.post(
        "/api/v1/external/users",
        content=raw,
        headers=_sign_headers(api_key["key_id"], api_key["secret"], raw, idem="idem-default"),
    )
    assert resp.status_code == 201, resp.text
    created = (
        await db_session.execute(select(User).where(User.id == UUID(resp.json()["id"])))
    ).scalar_one()
    assert created.user_type == "consumer"
    assert created.parent_user_id is None
