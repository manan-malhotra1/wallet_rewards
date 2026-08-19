"""Service catalog changes are recorded in the audit trail.

Every create / update / soft-delete of a catalog service is an administrator
action and must land an immutable `audit_log` row.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Service, Tenant

_ADMIN_SUB = "00000000-0000-4000-8000-000000000001"


async def _seed_base(session: AsyncSession, tenant_id: str, code: str) -> Service:
    """Persist an active base service so a derived create has something to point at."""
    row = Service(tenant_id=tenant_id, code=code, display_name=code.upper(), kind="base")
    session.add(row)
    await session.commit()
    return row


async def _audit_rows(db_session: AsyncSession, *, entity_id: str, action: str) -> list[AuditLog]:
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "service",
            AuditLog.entity_id == entity_id,
            AuditLog.action == action,
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_create_service_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a service is recorded in the audit trail"""
    await _seed_base(db_session, str(test_tenant.id), "airtime_recharge")
    resp = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "airtime",
            "display_name": "Airtime",
            "base_service_code": "airtime_recharge",
        },
    )
    assert resp.status_code == 201, resp.text
    service_id = resp.json()["id"]

    rows = await _audit_rows(db_session, entity_id=service_id, action="service.created")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.actor_id == _ADMIN_SUB
    assert row.after_state["code"] == "airtime"


@pytest.mark.asyncio
async def test_update_service_writes_before_after_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify editing a service is recorded in the audit trail with the old and new values"""
    await _seed_base(db_session, str(test_tenant.id), "airtime_recharge")
    create = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "topup",
            "display_name": "Top Up",
            "base_service_code": "airtime_recharge",
        },
    )
    service_id = create.json()["id"]
    resp = await async_client.patch(
        f"/api/v1/services/{service_id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"status": "disabled"},
    )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(db_session, entity_id=service_id, action="service.updated")
    assert len(rows) == 1
    row = rows[0]
    assert row.before_state["status"] == "active"
    assert row.after_state["status"] == "disabled"


@pytest.mark.asyncio
async def test_soft_delete_service_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify deleting a service is recorded in the audit trail"""
    await _seed_base(db_session, str(test_tenant.id), "airtime_recharge")
    create = await async_client.post(
        "/api/v1/services",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "gonesoon",
            "display_name": "Gone Soon",
            "base_service_code": "airtime_recharge",
        },
    )
    service_id = create.json()["id"]
    resp = await async_client.delete(
        f"/api/v1/services/{service_id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(db_session, entity_id=service_id, action="service.deleted")
    assert len(rows) == 1
    assert rows[0].before_state["code"] == "gonesoon"
