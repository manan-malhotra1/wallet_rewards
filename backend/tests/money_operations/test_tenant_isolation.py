"""Treasury moves stay within one tenant."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import LedgerEntry, Tenant, User
from tests.money_operations.conftest import (
    approve,
    ops_url,
    propose,
    seed_bank_mirror,
    seed_user_wallet,
    user_phone,
)


@pytest.mark.asyncio
async def test_request_not_visible_across_tenants(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify one tenant cannot see another tenant's treasury move"""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "A-only"},
    )
    resp = await async_client.get(ops_url(other_tenant, f"/{proposed['id']}"), headers=maker_header)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_across_tenants_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify one tenant cannot approve another tenant's treasury move"""
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "A-only"},
    )
    resp = await approve(async_client, other_tenant, proposed["id"], checker_header)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(
    async_client: AsyncClient,
    test_tenant: Tenant,
    other_tenant: Tenant,
    maker_header: dict[str, str],
) -> None:
    """Verify the moves list shows only the current tenant's moves"""
    await propose(
        async_client,
        test_tenant,
        maker_header,
        "create_bank_mirror",
        {"currency": "ZAR", "name": "A"},
    )
    resp = await async_client.get(ops_url(other_tenant), headers=maker_header)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_ledger_balances_to_zero_after_apply(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    maker_header: dict[str, str],
    checker_header: dict[str, str],
) -> None:
    """Verify the books still balance after a treasury move is applied

    A withdraw posts a balanced 2-leg transaction through `post_transaction`, so
    debits and credits net to zero across the tenant's accounts.
    """
    await seed_user_wallet(db_session, test_tenant, test_user, balance=Decimal("500"))
    mirror = await seed_bank_mirror(db_session, test_tenant)
    proposed = await propose(
        async_client,
        test_tenant,
        maker_header,
        "withdraw_user",
        {
            "identifier_type": "phone",
            "identifier_value": user_phone(test_user),
            "amount": "200",
            "currency": "ZAR",
            "bank_mirror_account_id": str(mirror.id),
            "reason": "cash-out",
        },
    )
    approved = await approve(async_client, test_tenant, proposed["id"], checker_header)
    assert approved.json()["status"] == "APPLIED"

    # The test DB is truncated per test, so every ledger entry here belongs to
    # this test's tenant — a whole-table sum is the tenant's ledger.
    credits = (
        await db_session.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.entry_type == "CREDIT"
            )
        )
    ).scalar_one()
    debits = (
        await db_session.execute(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.entry_type == "DEBIT"
            )
        )
    ).scalar_one()
    assert credits == debits
