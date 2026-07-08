"""Admin CRUD for external-API keys (Epic 14 S2).

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
from app.shared.models import ApiKey, Tenant


@pytest.mark.asyncio
async def test_create_returns_secret_once_and_stores_it_encrypted(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Create returns a usable key_id + plaintext secret once; the secret is
    stored only encrypted and never appears in the list response."""
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
async def test_create_requires_auth(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """No admin token -> 401."""
    resp = await async_client.post("/api/v1/api-keys", json={"tenant_id": str(test_tenant.id)})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_forbidden_without_platform_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    make_admin_token: Callable[..., str],
) -> None:
    """A token lacking platform-admin -> 403."""
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
    """Creating a key for a non-existent tenant -> 404."""
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
    """Listing a tenant's keys never returns another tenant's keys."""
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
    """Revoke flips status to revoked; revoking under the wrong tenant -> 404."""
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
