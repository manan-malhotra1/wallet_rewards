"""Viewing the operator wallets."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.service import fund
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Tenant,
    User,
)


@pytest.mark.asyncio
async def test_list_system_wallets_returns_system_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can see every operator wallet with its balance"""
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=None,
            account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            currency="PTS",
        )
    )
    await db_session.commit()

    response = await async_client.get(
        "/api/v1/treasury/system-wallets",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    types = [r["account_type"] for r in rows]
    assert ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE in types
    # Every row has a numeric balance field — even unused accounts.
    for r in rows:
        Decimal(str(r["balance"]))


@pytest.mark.asyncio
async def test_list_system_wallets_excludes_user_owned(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify customer wallets do not appear in the operator wallet list"""
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    response = await async_client.get(
        "/api/v1/treasury/system-wallets",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200
    # All returned accounts are system-owned (user_id is implicit — not in
    # the payload, but balance + type are present).
    for r in response.json():
        # Crude check: financial_wallet rows in the response would only
        # exist if a user wallet leaked in.
        assert r["account_type"] != ACCOUNT_TYPE_FINANCIAL_WALLET


@pytest.mark.asyncio
async def test_system_wallet_transactions_drill_down(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can drill into an operator wallet's transactions"""
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    await fund(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        amount=Decimal("100"),
        currency="ZAR",
        idempotency_key=f"top-{uuid4().hex[:8]}",
    )

    wallets = await async_client.get(
        "/api/v1/treasury/system-wallets",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    cash_inflow = next(r for r in wallets.json() if r["account_type"] == "system_cash_inflow")

    txns = await async_client.get(
        f"/api/v1/treasury/system-wallets/{cash_inflow['id']}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert txns.status_code == 200, txns.text
    rows = txns.json()
    assert len(rows) >= 1
    assert any(
        r["entry_type"] == "DEBIT" and Decimal(r["entry_amount"]) == Decimal("100") for r in rows
    )
    # Every drill-down row carries the parent transaction's customer reference.
    import re

    assert all(re.match(r"^S_\d{14}\d{6,}$", r["reference"]) for r in rows)


@pytest.mark.asyncio
async def test_transactions_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot view another tenant's operator wallet transactions"""
    acct = Account(
        tenant_id=test_tenant.id,
        user_id=None,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)

    response = await async_client.get(
        f"/api/v1/treasury/system-wallets/{acct.id}/transactions",
        params={"tenant_id": str(other_tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_transactions_unknown_account_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify viewing transactions for an account that does not exist is refused"""
    response = await async_client.get(
        f"/api/v1/treasury/system-wallets/{uuid4()}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 404
