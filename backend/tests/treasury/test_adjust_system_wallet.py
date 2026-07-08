"""Tests for POST /api/v1/treasury/adjust-system-wallet (fund/withdraw float)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    Account,
    Tenant,
)


async def _seed_system_cash_inflow(
    session: AsyncSession, tenant: Tenant, currency: str = "ZAR"
) -> Account:
    """Insert a system_cash_inflow account for the tenant."""
    acct = Account(
        tenant_id=tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
        currency=currency,
    )
    session.add(acct)
    await session.commit()
    await session.refresh(acct)
    return acct


@pytest.mark.asyncio
async def test_fund_float_credits_target_and_debits_operator(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Positive amount: target balance goes up, operator_adjustment goes down."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "1000000",
            "reason": "Initial R 1M float wire from Standard Bank.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["amount"]) == Decimal("1000000")
    assert Decimal(body["new_balance"]) == Decimal("1000000")

    # operator_adjustment should now show -1,000,000.
    from sqlalchemy import select

    op_acct = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
            )
        )
    ).scalar_one()
    op_balance, _ = await derive_balance(db_session, op_acct.id)
    assert op_balance == Decimal("-1000000")


@pytest.mark.asyncio
async def test_withdraw_float_debits_target_and_credits_operator(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Negative amount: target goes down, operator_adjustment goes up."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)

    # First fund R 500K.
    await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "500000",
            "reason": "seed fund",
        },
    )
    # Now withdraw R 100K.
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "-100000",
            "reason": "Ops expense — server bill.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["new_balance"]) == Decimal("400000")


@pytest.mark.asyncio
async def test_adjust_zero_amount_rejected(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Zero adjustment is meaningless → 422."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(target.id),
            "amount": "0",
            "reason": "no-op",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "amount_zero"


@pytest.mark.asyncio
async def test_adjust_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Adjusting another tenant's account must return 404."""
    target = await _seed_system_cash_inflow(db_session, test_tenant)
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(other_tenant.id),
            "account_id": str(target.id),
            "amount": "1000",
            "reason": "cross-tenant attempt",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_adjust_operator_adjustment_directly(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """operator_adjustment is the counter-leg; targeting it directly rejects."""
    op_acct = Account(
        tenant_id=test_tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
        currency="ZAR",
    )
    db_session.add(op_acct)
    await db_session.commit()
    await db_session.refresh(op_acct)

    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(op_acct.id),
            "amount": "1000",
            "reason": "shouldnt work",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "cannot_adjust_operator_adjustment"


@pytest.mark.asyncio
async def test_adjust_unknown_account_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Unknown account_id → 404."""
    response = await async_client.post(
        "/api/v1/treasury/adjust-system-wallet",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "account_id": str(uuid4()),
            "amount": "1000",
            "reason": "test",
        },
    )
    assert response.status_code == 404
