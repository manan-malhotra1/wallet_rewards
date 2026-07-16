"""Audit-trail tests for the roles admin endpoints (NFR-0160 / NFR-0250).

Authorization edits govern who may move money, so every role / permission /
binding mutation must land an immutable `audit_log` row. These tests hit the
`/api/v1/roles/*` and `/api/v1/users/{id}/roles*` endpoints (pre-authed by the
package conftest) and assert the row exists with the right actor / action /
entity / before-after state.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant, User

# The conftest admin token's `sub` claim — the audit actor_id we expect.
_ADMIN_SUB = "00000000-0000-4000-8000-000000000001"


async def _audit_rows(
    db_session: AsyncSession, *, entity_type: str, entity_id: str, action: str
) -> list[AuditLog]:
    """Fetch audit rows matching an (entity_type, entity_id, action) tuple."""
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
            AuditLog.action == action,
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_create_role_writes_audit(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    resp = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "audit-role", "description": "d"},
    )
    assert resp.status_code == 201, resp.text
    role_id = resp.json()["id"]

    rows = await _audit_rows(
        db_session, entity_type="role", entity_id=role_id, action="role.created"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.actor_id == _ADMIN_SUB
    assert row.after_state is not None
    assert row.after_state["name"] == "audit-role"


@pytest.mark.asyncio
async def test_update_role_writes_before_after_audit(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "to-update"},
    )
    role_id = create.json()["id"]
    resp = await async_client.patch(
        f"/api/v1/roles/{role_id}",
        params={"tenant_id": str(test_tenant.id)},
        json={"status": "inactive"},
    )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(
        db_session, entity_type="role", entity_id=role_id, action="role.updated"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.before_state["status"] == "active"
    assert row.after_state["status"] == "inactive"


@pytest.mark.asyncio
async def test_set_permission_writes_grant_audit(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Granting a permission on a role is the money-relevant edit — audit it."""
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "perm-role"},
    )
    role_id = create.json()["id"]
    resp = await async_client.post(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
        json={"transaction_type": "p2p", "permitted": True},
    )
    assert resp.status_code == 201, resp.text

    rows = await _audit_rows(
        db_session, entity_type="role", entity_id=role_id, action="role.permission_granted"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.after_state["transaction_type"] == "p2p"
    assert row.after_state["permitted"] is True


@pytest.mark.asyncio
async def test_remove_permission_writes_revoke_audit(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "revoke-role"},
    )
    role_id = create.json()["id"]
    await async_client.post(
        f"/api/v1/roles/{role_id}/permissions",
        params={"tenant_id": str(test_tenant.id)},
        json={"transaction_type": "bill_pay", "permitted": True},
    )
    resp = await async_client.delete(
        f"/api/v1/roles/{role_id}/permissions/bill_pay",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204, resp.text

    rows = await _audit_rows(
        db_session, entity_type="role", entity_id=role_id, action="role.permission_revoked"
    )
    assert len(rows) == 1
    assert rows[0].before_state["transaction_type"] == "bill_pay"


@pytest.mark.asyncio
async def test_assign_role_writes_binding_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "assign-role"},
    )
    role_id = create.json()["id"]
    resp = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    assert resp.status_code == 201, resp.text
    binding_id = resp.json()["id"]

    rows = await _audit_rows(
        db_session,
        entity_type="user_role",
        entity_id=binding_id,
        action="user.role_assigned",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.after_state["user_id"] == str(test_user.id)
    assert row.after_state["role_id"] == role_id


@pytest.mark.asyncio
async def test_idempotent_reassign_writes_no_second_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Re-assigning an existing binding is a no-op — it must not double-audit."""
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "dup-assign"},
    )
    role_id = create.json()["id"]
    first = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    binding_id = first.json()["id"]
    await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )

    rows = await _audit_rows(
        db_session,
        entity_type="user_role",
        entity_id=binding_id,
        action="user.role_assigned",
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_remove_role_writes_binding_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    create = await async_client.post(
        "/api/v1/roles",
        json={"tenant_id": str(test_tenant.id), "name": "remove-role"},
    )
    role_id = create.json()["id"]
    assign = await async_client.post(
        f"/api/v1/users/{test_user.id}/roles",
        params={"tenant_id": str(test_tenant.id)},
        json={"role_id": role_id},
    )
    binding_id = assign.json()["id"]
    resp = await async_client.delete(
        f"/api/v1/users/{test_user.id}/roles/{role_id}",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 204, resp.text

    rows = await _audit_rows(
        db_session,
        entity_type="user_role",
        entity_id=binding_id,
        action="user.role_removed",
    )
    assert len(rows) == 1
    assert rows[0].before_state["role_id"] == role_id
