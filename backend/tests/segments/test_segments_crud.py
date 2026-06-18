"""Tests for /api/v1/segments admin CRUD + membership."""
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


@pytest.mark.asyncio
async def test_create_segment_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """POST returns 201 + the persisted row."""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "name": "vip-users",
            "description": "Top 1% by lifetime spend.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "vip-users"
    assert body["tenant_id"] == str(test_tenant.id)


@pytest.mark.asyncio
async def test_create_segment_duplicate_name_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Same name twice within the tenant → 409."""
    payload = {"tenant_id": str(test_tenant.id), "name": "dup"}
    a = await async_client.post(
        "/api/v1/segments", headers=admin_auth_header, json=payload
    )
    assert a.status_code == 201
    b = await async_client.post(
        "/api/v1/segments", headers=admin_auth_header, json=payload
    )
    assert b.status_code == 409
    assert b.json()["error_code"] == "segment_already_exists"


@pytest.mark.asyncio
async def test_list_segments_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Listing returns only the requesting tenant's rows."""
    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "in-tenant"},
    )
    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(other_tenant.id), "name": "other-tenant"},
    )
    resp = await async_client.get(
        "/api/v1/segments",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert names == ["in-tenant"]


@pytest.mark.asyncio
async def test_add_user_to_segment_idempotent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Adding the same user twice is a no-op (no duplicate row)."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "early-adopters"},
    )
    seg_id = create.json()["id"]

    a = await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"user_id": str(test_user.id)},
    )
    b = await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"user_id": str(test_user.id)},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["user_id"] == str(test_user.id)


@pytest.mark.asyncio
async def test_add_user_cross_tenant_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Adding a user to a segment in a different tenant → 404."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "scope-test"},
    )
    seg_id = create.json()["id"]

    resp = await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(other_tenant.id)},
        json={"user_id": str(test_user.id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_unknown_user_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Unknown user_id → 404."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "unknown-user-test"},
    )
    seg_id = create.json()["id"]

    resp = await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"user_id": str(uuid4())},
    )
    assert resp.status_code == 404
