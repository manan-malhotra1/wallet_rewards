"""Managing customer segments."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.shared.models import Tenant, User


@pytest.mark.asyncio
async def test_create_segment_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can create a customer segment"""
    resp = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "vip-users",
            "description": "Top 1% by lifetime spend.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "vip-users"
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["group_id"] == test_segment_group
    assert body["priority"] == 0
    assert body["criteria"] is None
    assert body["is_system"] is False
    assert body["last_evaluated_at"] is None


@pytest.mark.asyncio
async def test_create_segment_duplicate_name_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a segment cannot reuse an existing segment name within the same group."""
    payload = {
        "tenant_id": str(test_tenant.id),
        "group_id": test_segment_group,
        "name": "dup",
    }
    a = await async_client.post("/api/v1/segments", headers=admin_auth_header, json=payload)
    assert a.status_code == 201
    b = await async_client.post("/api/v1/segments", headers=admin_auth_header, json=payload)
    assert b.status_code == 409
    assert b.json()["error_code"] == "segment_already_exists"


@pytest.mark.asyncio
async def test_create_segment_duplicate_name_ok_in_different_group(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the same segment name is free to reuse in a DIFFERENT group.

    Proves the uniqueness constraint is now scoped per (tenant, group), not
    tenant-wide (see `Segment.__table_args__`'s `uq_segments_name_per_group`).
    """
    other_group_id = await make_segment_group(test_tenant.id)

    a = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "rescoped-dup",
        },
    )
    assert a.status_code == 201

    b = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": other_group_id,
            "name": "rescoped-dup",
        },
    )
    assert b.status_code == 201, b.text


@pytest.mark.asyncio
async def test_list_segments_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a business only sees its own customer segments"""
    in_tenant_group = await make_segment_group(test_tenant.id)
    other_tenant_group = await make_segment_group(other_tenant.id)

    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": in_tenant_group,
            "name": "in-tenant",
        },
    )
    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "group_id": other_tenant_group,
            "name": "other-tenant",
        },
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
    test_segment_group: str,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a customer to a segment twice does not duplicate them"""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "early-adopters",
        },
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
    test_segment_group: str,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a customer cannot be added to another business's segment"""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "scope-test",
        },
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
async def test_rename_segment_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify PATCH with a `name` field renames the segment."""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "old-name",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "new-name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "new-name"


@pytest.mark.asyncio
async def test_rename_segment_duplicate_in_group_409(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify renaming a segment to a name already used in the SAME group 409s."""
    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "taken",
        },
    )
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "renamable",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "taken"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "segment_already_exists"


@pytest.mark.asyncio
async def test_rename_segment_same_name_ok_in_different_group(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    make_segment_group: Callable[..., Awaitable[str]],
    admin_auth_header: dict[str, str],
) -> None:
    """Verify renaming to a name already used in a DIFFERENT group is fine.

    Proves the rename path shares the create path's (tenant, group) scoping
    on `uq_segments_name_per_group`, not a tenant-wide check.
    """
    other_group_id = await make_segment_group(test_tenant.id)
    await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": other_group_id,
            "name": "shared-name",
        },
    )
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "renamable-2",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.patch(
        f"/api/v1/segments/{seg_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"name": "shared-name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "shared-name"


@pytest.mark.asyncio
async def test_add_unknown_user_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_segment_group: str,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an unknown customer cannot be added to a segment"""
    create = await async_client.post(
        "/api/v1/segments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "group_id": test_segment_group,
            "name": "unknown-user-test",
        },
    )
    seg_id = create.json()["id"]

    resp = await async_client.post(
        f"/api/v1/segments/{seg_id}/users",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
        json={"user_id": str(uuid4())},
    )
    assert resp.status_code == 404
