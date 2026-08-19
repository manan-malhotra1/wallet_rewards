"""Display-name enrichment on money-operation reads (Epic 18).

The UI renders wallet / bank-mirror / user names, never raw UUIDs, so both the
list endpoint AND the single-operation fetch (the detail drawer's refresh path)
must attach `account_name` / `bank_mirror_name`. A regression here shows
operators bare account ids on a money-movement approval.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import Tenant
from tests.money_operations.conftest import (
    ops_url,
    propose,
    seed_bank_mirror,
    seed_system_wallet,
)


async def _propose_adjust(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tenant: Tenant,
    maker_header: dict[str, str],
) -> dict:
    """Propose an adjust against an unnamed system wallet + a named mirror."""
    target = await seed_system_wallet(db_session, tenant)
    mirror = await seed_bank_mirror(db_session, tenant, name="Steward Bank")
    return await propose(
        async_client,
        tenant,
        maker_header,
        "adjust_system_wallet",
        {
            "account_id": str(target.id),
            "amount": "300",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "float top-up",
        },
    )


@pytest.mark.asyncio
async def test_get_single_operation_resolves_wallet_and_mirror_names(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify the detail fetch names both legs instead of leaving raw UUIDs"""
    proposed = await _propose_adjust(async_client, db_session, test_tenant, maker_header)
    resp = await async_client.get(ops_url(test_tenant, f"/{proposed['id']}"), headers=maker_header)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The target wallet has no custom name — its account_type is the fallback.
    assert body["account_name"] == "system_cash_inflow"
    assert body["bank_mirror_name"] == "Steward Bank"


@pytest.mark.asyncio
async def test_list_operations_resolves_wallet_and_mirror_names(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify the list endpoint names both legs of an adjust proposal"""
    proposed = await _propose_adjust(async_client, db_session, test_tenant, maker_header)
    resp = await async_client.get(ops_url(test_tenant), headers=maker_header)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["id"] == proposed["id"])
    assert row["account_name"] == "system_cash_inflow"
    assert row["bank_mirror_name"] == "Steward Bank"
