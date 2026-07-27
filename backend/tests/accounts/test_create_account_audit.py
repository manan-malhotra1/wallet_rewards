"""Auditing account creation.

Account creation is an administrator action, so it must land an immutable
`audit_log` row with the owner scope + type/currency (never secrets).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant, User

_ADMIN_SUB = "00000000-0000-4000-8000-000000000001"


@pytest.mark.asyncio
async def test_create_account_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify opening an account is recorded in the audit trail"""
    resp = await async_client.post(
        "/api/v1/accounts",
        json={
            "tenant_id": str(test_tenant.id),
            "user_id": str(test_user.id),
            "account_type": "financial_wallet",
            "currency": "ZAR",
        },
    )
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["id"]

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "account",
                    AuditLog.entity_id == account_id,
                    AuditLog.action == "account.created",
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
    assert row.after_state is not None
    assert row.after_state["account_type"] == "financial_wallet"
    assert row.after_state["currency"] == "ZAR"
    assert row.after_state["user_id"] == str(test_user.id)
