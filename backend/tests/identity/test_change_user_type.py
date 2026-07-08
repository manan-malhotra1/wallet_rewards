"""Tests for PATCH /api/v1/identity/users/{user_id}/type (Epic 12).

Covers the happy path, Decision-D4 parent rules on type change, mandatory
reason, RBAC (401/403), tenant isolation (404), and state-based idempotency
(a repeated identical change writes no second audit row).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant


async def _create_user(
    client: AsyncClient,
    headers: dict[str, str],
    tenant: Tenant,
    *,
    phone: str,
    user_type: str | None = None,
) -> dict:
    """Create a user via the API and return the response body."""
    payload: dict = {
        "tenant_id": str(tenant.id),
        "identifiers": [{"identifier_type": "phone", "identifier_value": phone}],
    }
    if user_type is not None:
        payload["user_type"] = user_type
    response = await client.post("/api/v1/identity/users", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _patch_type(
    client: AsyncClient,
    headers: dict[str, str] | None,
    *,
    user_id: str,
    tenant: Tenant,
    new_type: str,
    parent_user_id: str | None = None,
    reason: str | None = "operator correction",
) -> tuple[int, dict]:
    """PATCH a user's type and return (status_code, body)."""
    body: dict = {"new_type": new_type}
    if parent_user_id is not None:
        body["parent_user_id"] = parent_user_id
    if reason is not None:
        body["reason"] = reason
    response = await client.patch(
        f"/api/v1/identity/users/{user_id}/type",
        params={"tenant_id": str(tenant.id)},
        headers=headers or {},
        json=body,
    )
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_change_type_happy_path(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A consumer can be promoted to super_agent."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2000")
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
    )
    assert status == 200, body
    assert body["user_type"] == "super_agent"
    assert body["parent_user_id"] is None


@pytest.mark.asyncio
async def test_change_type_attaches_valid_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Changing a user to agent under a super_agent parent succeeds."""
    parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 2001",
        user_type="super_agent",
    )
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2002")
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="agent",
        parent_user_id=parent["id"],
    )
    assert status == 200, body
    assert body["user_type"] == "agent"
    assert body["parent_user_id"] == parent["id"]


@pytest.mark.asyncio
async def test_change_type_rejects_incompatible_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Changing to agent under a consumer parent is rejected 422."""
    consumer_parent = await _create_user(
        async_client, admin_auth_header, test_tenant, phone="+27 82 555 2003"
    )
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2004")
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="agent",
        parent_user_id=consumer_parent["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_change_to_toplevel_type_rejects_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Changing to consumer while supplying a parent is rejected 422."""
    parent = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 2005",
        user_type="super_agent",
    )
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2006")
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="consumer",
        parent_user_id=parent["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_change_type_rejects_self_parent(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """A user cannot be set as its own parent (422), even if types would match."""
    user = await _create_user(
        async_client,
        admin_auth_header,
        test_tenant,
        phone="+27 82 555 2007",
        user_type="super_agent",
    )
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="agent",
        parent_user_id=user["id"],
    )
    assert status == 422, body
    assert body["error_code"] == "user_type_invalid_parent"


@pytest.mark.asyncio
async def test_change_type_requires_reason(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An empty reason fails validation (422) — reason is mandatory for audit."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2008")
    status, _ = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
        reason="",
    )
    assert status == 422


@pytest.mark.asyncio
async def test_change_type_rejects_invalid_type(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An unknown new_type fails Pydantic Literal validation (422)."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2009")
    status, _ = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="wholesaler",
    )
    assert status == 422


@pytest.mark.asyncio
async def test_change_type_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """No Authorization header → 401."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2010")
    status, _ = await _patch_type(
        async_client,
        None,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
    )
    assert status == 401


@pytest.mark.asyncio
async def test_change_type_forbids_non_admin(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
    make_admin_token,
) -> None:
    """A token without the platform-admin role → 403."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2011")
    non_admin = {"Authorization": f"Bearer {make_admin_token(roles=['viewer'])}"}
    status, _ = await _patch_type(
        async_client,
        non_admin,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
    )
    assert status == 403


@pytest.mark.asyncio
async def test_change_type_tenant_isolation(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Changing a user via the wrong tenant_id returns 404 (no existence leak)."""
    user = await _create_user(
        async_client, admin_auth_header, other_tenant, phone="+27 82 555 2012"
    )
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,  # wrong tenant for this user
        new_type="super_agent",
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_change_type_unknown_user(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """An unknown user_id returns 404."""
    status, body = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=str(uuid4()),
        tenant=test_tenant,
        new_type="super_agent",
    )
    assert status == 404, body
    assert body["error_code"] == "user_not_found"


@pytest.mark.asyncio
async def test_change_type_is_idempotent(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Repeating the same change is a no-op — exactly one audit row is written."""
    user = await _create_user(async_client, admin_auth_header, test_tenant, phone="+27 82 555 2013")
    first = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
    )
    second = await _patch_type(
        async_client,
        admin_auth_header,
        user_id=user["id"],
        tenant=test_tenant,
        new_type="super_agent",
    )
    assert first[0] == 200 and second[0] == 200
    assert second[1]["user_type"] == "super_agent"

    # Idempotency guarantee: the second (no-op) call wrote NO extra audit row.
    await db_session.rollback()  # fresh snapshot so we see committed rows
    count = await db_session.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.entity_id == user["id"],
            AuditLog.action == "user.type_changed",
        )
    )
    assert count.scalar_one() == 1
