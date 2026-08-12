"""Managing partner API keys.

Create (secret shown once), list (secret never returned), revoke
(tenant-isolated). platform-admin gated; happy + 401/403/404 + tenant scope.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.secret_box import decrypt_secret
from app.shared.models import (
    USER_TYPE_CONSUMER,
    USER_TYPE_MERCHANT,
    ApiKey,
    AuditLog,
    Tenant,
    User,
)


async def _make_user(session: AsyncSession, tenant_id: object, user_type: str) -> User:
    """Persist a bare user of the given type in the tenant, return it."""
    user = User(tenant_id=tenant_id, user_type=user_type)
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_create_returns_secret_once_and_stores_it_encrypted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a new API key's secret is shown only once and never stored in the clear"""
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "label": "partner-acme"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key_id"].startswith("sak_")
    assert len(body["secret"]) >= 20
    assert body["status"] == "active"
    assert body["label"] == "partner-acme"

    # Stored encrypted, and decrypts back to exactly the returned secret.
    row = (
        await db_session.execute(select(ApiKey).where(ApiKey.key_id == body["key_id"]))
    ).scalar_one()
    assert row.secret_encrypted != body["secret"]
    assert decrypt_secret(row.secret_encrypted) == body["secret"]

    # The list view never leaks the secret.
    listing = await async_client.get(
        "/api/v1/api-keys", headers=admin_auth_header, params={"tenant_id": str(test_tenant.id)}
    )
    assert listing.status_code == 200
    keys = listing.json()
    assert len(keys) == 1
    assert "secret" not in keys[0]
    assert keys[0]["key_id"] == body["key_id"]


@pytest.mark.asyncio
async def test_create_without_merchant_user_leaves_it_null(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an API key can be created without linking it to a merchant"""
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["merchant_user_id"] is None
    row = (
        await db_session.execute(select(ApiKey).where(ApiKey.key_id == resp.json()["key_id"]))
    ).scalar_one()
    assert row.merchant_user_id is None


@pytest.mark.asyncio
async def test_create_with_merchant_user_binds_key_and_audits(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an API key can be linked to a merchant and the change is audited"""
    merchant = await _make_user(db_session, test_tenant.id, USER_TYPE_MERCHANT)
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "merchant_user_id": str(merchant.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["merchant_user_id"] == str(merchant.id)

    # Row bound — this is what ApiKeyPrincipal copies to authorise merchant-cashin.
    row = (
        await db_session.execute(select(ApiKey).where(ApiKey.key_id == resp.json()["key_id"]))
    ).scalar_one()
    assert row.merchant_user_id == merchant.id

    # Audit after_state carries the (non-secret) merchant binding.
    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "api_key.created",
                AuditLog.entity_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit.after_state is not None
    assert audit.after_state["merchant_user_id"] == str(merchant.id)
    assert "secret" not in audit.after_state


@pytest.mark.asyncio
async def test_create_with_non_merchant_user_422_and_no_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an API key cannot be linked to a non-merchant user"""
    consumer = await _make_user(db_session, test_tenant.id, USER_TYPE_CONSUMER)
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "merchant_user_id": str(consumer.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "merchant_user_required"
    count = (
        (await db_session.execute(select(ApiKey).where(ApiKey.tenant_id == test_tenant.id)))
        .scalars()
        .all()
    )
    assert count == []


@pytest.mark.asyncio
async def test_create_with_unknown_merchant_user_422_and_no_key(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an API key cannot be linked to an unknown user"""
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "merchant_user_id": str(uuid4())},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "merchant_user_required"
    keys = (
        (await db_session.execute(select(ApiKey).where(ApiKey.tenant_id == test_tenant.id)))
        .scalars()
        .all()
    )
    assert keys == []


@pytest.mark.asyncio
async def test_create_with_merchant_user_from_another_tenant_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an API key cannot be linked to a merchant from another business"""
    foreign_merchant = await _make_user(db_session, other_tenant.id, USER_TYPE_MERCHANT)
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "merchant_user_id": str(foreign_merchant.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "merchant_user_required"
    keys = (
        (await db_session.execute(select(ApiKey).where(ApiKey.tenant_id == test_tenant.id)))
        .scalars()
        .all()
    )
    assert keys == []


@pytest.mark.asyncio
async def test_create_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify creating an API key requires an administrator to sign in"""
    resp = await async_client.post("/api/v1/api-keys", json={"tenant_id": str(test_tenant.id)})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_forbidden_without_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """Verify only a platform administrator can create an API key"""
    token = make_admin_token(roles=["support-agent"])
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_unknown_tenant_404(
    async_client: AsyncClient, admin_auth_header: dict[str, str]
) -> None:
    """Verify an API key cannot be created for an unknown business"""
    resp = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(uuid4())},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one business only sees its own API keys"""
    for tid, label in ((test_tenant.id, "a"), (other_tenant.id, "b")):
        await async_client.post(
            "/api/v1/api-keys",
            headers=admin_auth_header,
            json={"tenant_id": str(tid), "label": label},
        )
    listing = await async_client.get(
        "/api/v1/api-keys", headers=admin_auth_header, params={"tenant_id": str(other_tenant.id)}
    )
    assert listing.status_code == 200
    keys = listing.json()
    assert [k["label"] for k in keys] == ["b"]


@pytest.mark.asyncio
async def test_revoke_sets_status_and_is_tenant_isolated(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an administrator can revoke an API key only within their own business"""
    created = await async_client.post(
        "/api/v1/api-keys",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id)},
    )
    key_pk = created.json()["id"]

    # Wrong tenant can't revoke it.
    cross = await async_client.post(
        f"/api/v1/api-keys/{key_pk}/revoke",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
    )
    assert cross.status_code == 404

    ok = await async_client.post(
        f"/api/v1/api-keys/{key_pk}/revoke",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "revoked"
