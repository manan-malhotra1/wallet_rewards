"""Every user change is recorded in the audit trail."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant
from tests.user_operations.conftest import (
    approve,
    create_user_payload,
    propose,
)


async def _actions(session: AsyncSession, tenant: Tenant, entity_type: str) -> list[str]:
    """Audit actions recorded for a tenant + entity_type, oldest-first."""
    rows = await session.execute(
        select(AuditLog.action)
        .where(AuditLog.tenant_id == tenant.id, AuditLog.entity_type == entity_type)
        .order_by(AuditLog.created_at.asc())
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_propose_and_apply_write_audit_rows(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify proposing and approving a user change is fully recorded in the audit trail"""
    proposed = await propose(
        async_client, test_tenant, maker_header, "create_user", create_user_payload()
    )
    await approve(async_client, test_tenant, proposed["id"], checker_header)

    actions = await _actions(db_session, test_tenant, "user_operation_request")
    assert "user_op.proposed" in actions
    assert "user_op.approved" in actions
    assert "user_op.applied" in actions
