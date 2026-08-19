"""Offset pagination for the audit log (B7.3 — the table grows for 7 years).

The endpoint already capped `limit`; without `offset` the UI could never page
past the first window of an ever-growing log.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant
from tests.reconciliation.test_audit_enrichment import _add_audit_row, _get_audit


async def _seed_rows(db_session: AsyncSession, tenant: Tenant, count: int) -> list[str]:
    """Insert `count` audit rows; return their entity_ids in insert order."""
    entity_ids = []
    for i in range(count):
        row = await _add_audit_row(
            db_session,
            tenant,
            actor_id="admin-x",
            actor_type="admin",
            entity_type="page-test",
            entity_id=f"entity-{i}",
        )
        entity_ids.append(row.entity_id)
    return entity_ids


@pytest.mark.asyncio
async def test_audit_offset_windows_newest_first(
    async_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify limit/offset slice the newest-first audit log into stable windows."""
    ids = await _seed_rows(db_session, test_tenant, 3)

    window = await _get_audit(async_client, test_tenant, entity_type="page-test", limit=2)
    assert [r["entity_id"] for r in window] == [ids[2], ids[1]]

    window = await _get_audit(
        async_client, test_tenant, entity_type="page-test", limit=2, offset=2
    )
    assert [r["entity_id"] for r in window] == [ids[0]]


@pytest.mark.asyncio
async def test_audit_offset_bounds_422(async_client: AsyncClient, test_tenant: Tenant) -> None:
    """Verify a negative offset is rejected with 422, not clamped."""
    resp = await async_client.get(
        "/api/v1/reconciliation/audit",
        params={"tenant_id": str(test_tenant.id), "offset": -1},
    )
    assert resp.status_code == 422
