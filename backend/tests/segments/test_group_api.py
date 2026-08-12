"""Segment-group CRUD API — admin create/list/delete with a guarded delete."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Segment, SegmentGroup, Tenant


@pytest.mark.asyncio
async def test_create_and_list_group_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can create a segment group and see it in the tenant list."""
    resp = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "name": "Customer Loyalty",
            "description": "Exclusive spend tiers.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Customer Loyalty"
    assert body["tenant_id"] == str(test_tenant.id)
    assert body["description"] == "Exclusive spend tiers."
    assert body["is_system"] is False
    assert "id" in body and "created_at" in body and "updated_at" in body

    listed = await async_client.get(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert listed.status_code == 200
    names = [g["name"] for g in listed.json()]
    assert names == ["Customer Loyalty"]


@pytest.mark.asyncio
async def test_create_group_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
) -> None:
    """Verify a segment group cannot be created without a valid admin token."""
    resp = await async_client.post(
        "/api/v1/segment-groups",
        headers={"Authorization": ""},
        json={"tenant_id": str(test_tenant.id), "name": "No Auth"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_group_empty_name_422(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an empty group name is rejected by validation."""
    resp = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_group_duplicate_name_409_but_ok_in_other_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a duplicate group name 409s within a tenant but is fine across tenants."""
    payload = {"tenant_id": str(test_tenant.id), "name": "dup-group"}
    a = await async_client.post("/api/v1/segment-groups", headers=admin_auth_header, json=payload)
    assert a.status_code == 201
    b = await async_client.post("/api/v1/segment-groups", headers=admin_auth_header, json=payload)
    assert b.status_code == 409
    assert b.json()["error_code"] == "segment_group_name_taken"

    other = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={"tenant_id": str(other_tenant.id), "name": "dup-group"},
    )
    assert other.status_code == 201


@pytest.mark.asyncio
async def test_delete_group_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deleting a group removes it from the list and writes an audit row."""
    create = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "to-delete"},
    )
    group_id = create.json()["id"]

    resp = await async_client.delete(
        f"/api/v1/segment-groups/{group_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204

    listed = await async_client.get(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert group_id not in [g["id"] for g in listed.json()]

    audit_row = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "segment_group.deleted",
                AuditLog.entity_id == group_id,
            )
        )
    ).scalar_one_or_none()
    assert audit_row is not None
    assert audit_row.before_state == {"name": "to-delete"}


@pytest.mark.asyncio
async def test_delete_group_404_unknown_and_cross_tenant(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deleting an unknown group, or one owned by another tenant, 404s."""
    unknown = await async_client.delete(
        f"/api/v1/segment-groups/{uuid4()}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert unknown.status_code == 404

    create = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={"tenant_id": str(other_tenant.id), "name": "belongs-to-other"},
    )
    group_id = create.json()["id"]

    cross_tenant = await async_client.delete(
        f"/api/v1/segment-groups/{group_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_delete_group_protected_409_for_system_group(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a system-seeded group cannot be deleted."""
    group = SegmentGroup(tenant_id=test_tenant.id, name="General", is_system=True)
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    resp = await async_client.delete(
        f"/api/v1/segment-groups/{group.id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "segment_group_protected"


@pytest.mark.asyncio
async def test_delete_group_not_empty_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a group still holding a segment cannot be deleted.

    The segment is attached via the ORM directly (not POST /api/v1/segments)
    because that endpoint doesn't accept `group_id` until Task 7.
    """
    create = await async_client.post(
        "/api/v1/segment-groups",
        headers=admin_auth_header,
        json={"tenant_id": str(test_tenant.id), "name": "non-empty"},
    )
    group_id = create.json()["id"]

    db_session.add(Segment(tenant_id=test_tenant.id, group_id=group_id, name="Gold"))
    await db_session.commit()

    resp = await async_client.delete(
        f"/api/v1/segment-groups/{group_id}",
        headers=admin_auth_header,
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "segment_group_not_empty"
