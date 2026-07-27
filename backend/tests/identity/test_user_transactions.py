"""Customer transaction history — an admin viewing a customer's recent transactions.

Admin-facing version of the mobile /me/wallet recent-transactions feed.
Shape matches WalletTransactionOut so the admin UI's table component
can share types with the mobile-simulator's.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger.service import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _seed_wallet_with_credit(
    session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    amount: Decimal,
    transaction_type: str = "fund",
) -> Account:
    """Give the user a ZAR wallet + post one CREDIT balanced txn."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    # Reuse the tenant's pre-funded cash float (get-or-create) — a second
    # system_cash_inflow row would violate the unique index; its positive balance
    # absorbs the bootstrap DEBIT below (the float has a no-overdraft floor).
    from app.modules.payments.service import get_or_create_system_cash_inflow

    inflow = await get_or_create_system_cash_inflow(session, tenant.id, "ZAR")

    await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant.id,
            idempotency_key=f"seed-{uuid4().hex}",
            transaction_type=transaction_type,
            currency="ZAR",
            amount=amount,
            entries=[
                LedgerEntryRequest(
                    account_id=inflow.id,
                    entry_type="DEBIT",
                    amount=amount,
                ),
                LedgerEntryRequest(
                    account_id=wallet.id,
                    entry_type="CREDIT",
                    amount=amount,
                ),
            ],
        ),
    )
    await session.commit()
    return wallet


@pytest.mark.asyncio
async def test_user_transactions_requires_auth(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
) -> None:
    """Verify viewing a customer's transactions requires signing in"""
    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_user_transactions_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin can see a customer's recent transactions"""
    await _seed_wallet_with_credit(db_session, test_tenant, test_user, amount=Decimal("500"))

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["transaction_type"] == "fund"
    assert row["direction"] == "in"
    assert Decimal(row["amount"]) == Decimal("500")
    assert row["currency"] == "ZAR"


@pytest.mark.asyncio
async def test_user_transactions_unknown_user_returns_404(
    async_client: AsyncClient,
    test_tenant: Tenant,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify viewing transactions for a customer who does not exist is rejected"""
    resp = await async_client.get(
        f"/api/v1/identity/users/{uuid4()}/transactions",
        params={"tenant_id": str(test_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_user_transactions_cross_tenant_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    other_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot see the transactions of a customer in another tenant"""
    await _seed_wallet_with_credit(db_session, test_tenant, test_user, amount=Decimal("100"))

    resp = await async_client.get(
        f"/api/v1/identity/users/{test_user.id}/transactions",
        params={"tenant_id": str(other_tenant.id)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
