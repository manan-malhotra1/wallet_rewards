"""Audit-trail test for PATCH /api/v1/tenants/{id} (NFR-0160 / NFR-0250).

Editing a tenant's identity card is an administrator action and must land an
immutable `audit_log` row with the before/after snapshot.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant

_ADMIN_SUB = "00000000-0000-4000-8000-000000000001"


@pytest.mark.asyncio
async def test_patch_tenant_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    new_name = f"renamed-{uuid4().hex[:8]}"
    old_name = test_tenant.name
    resp = await async_client.patch(
        f"/api/v1/tenants/{test_tenant.id}",
        headers=admin_auth_header,
        json={"name": new_name},
    )
    assert resp.status_code == 200, resp.text

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "tenant",
                    AuditLog.entity_id == str(test_tenant.id),
                    AuditLog.action == "tenant.updated",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.actor_id == _ADMIN_SUB
    assert row.before_state["name"] == old_name
    assert row.after_state["name"] == new_name
