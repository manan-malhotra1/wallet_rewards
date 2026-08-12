"""Currency catalog audit trail.

Every create / update / soft-delete of a catalog instrument is an
administrator action and must land an immutable `audit_log` row.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import AuditLog, Tenant

_ADMIN_SUB = "00000000-0000-4000-8000-000000000001"


async def _audit_rows(db_session: AsyncSession, *, entity_id: str, action: str) -> list[AuditLog]:
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "instrument",
            AuditLog.entity_id == entity_id,
            AuditLog.action == action,
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_create_instrument_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify adding a currency is recorded in the audit trail"""
    resp = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "USDC",
            "symbol": "$",
            "display_name": "USD Coin",
            "account_type": "financial_wallet",
        },
    )
    assert resp.status_code == 201, resp.text
    instrument_id = resp.json()["id"]

    rows = await _audit_rows(db_session, entity_id=instrument_id, action="instrument.created")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "admin"
    assert row.actor_id == _ADMIN_SUB
    assert row.after_state["code"] == "USDC"


@pytest.mark.asyncio
async def test_update_instrument_writes_before_after_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify editing a currency records its before and after state"""
    create = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "EURC",
            "symbol": "E",
            "display_name": "Euro Coin",
            "account_type": "financial_wallet",
        },
    )
    instrument_id = create.json()["id"]
    resp = await async_client.patch(
        f"/api/v1/instruments/{instrument_id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
        json={"status": "disabled"},
    )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(db_session, entity_id=instrument_id, action="instrument.updated")
    assert len(rows) == 1
    row = rows[0]
    assert row.before_state["status"] == "active"
    assert row.after_state["status"] == "disabled"


@pytest.mark.asyncio
async def test_soft_delete_instrument_writes_audit(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify removing a currency is recorded in the audit trail"""
    create = await async_client.post(
        "/api/v1/instruments",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "code": "GBPC",
            "symbol": "P",
            "display_name": "GBP Coin",
            "account_type": "financial_wallet",
        },
    )
    instrument_id = create.json()["id"]
    resp = await async_client.delete(
        f"/api/v1/instruments/{instrument_id}",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    rows = await _audit_rows(db_session, entity_id=instrument_id, action="instrument.deleted")
    assert len(rows) == 1
    assert rows[0].before_state["code"] == "GBPC"
