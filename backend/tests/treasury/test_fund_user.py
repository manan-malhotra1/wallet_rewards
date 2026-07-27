"""Topping up a customer wallet.

Epic 18: fund-user now PROPOSES a money operation; the fund posts only after a
distinct treasury-approver approves it. Body-level validation (amount, reason,
tenant) still fails at propose time; the max-balance guard fires at apply time.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
    WalletLimitConfig,
)
from tests.treasury.conftest import approve_op


def _user_phone(user: User) -> str:
    """Return the seeded phone identifier (test_user fixture creates one)."""
    return next(
        ident.identifier_value for ident in user.identifiers if ident.identifier_type == "phone"
    )


async def _seed_user_wallet(session: AsyncSession, tenant: Tenant, user: User) -> Account:
    """Give the user a ZAR financial wallet."""
    wallet = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
    )
    session.add(wallet)
    await session.commit()
    await session.refresh(wallet)
    return wallet


@pytest.mark.asyncio
async def test_fund_user_happy_path(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify an admin can top up a customer's wallet from the operator float"""
    wallet = await _seed_user_wallet(db_session, test_tenant, test_user)

    proposed = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "500",
            "currency": "ZAR",
            "reason": "Onboarding gift.",
        },
    )
    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["status"] == "PENDING"

    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPLIED"

    bal, _ = await derive_balance(db_session, wallet.id)
    assert bal == Decimal("500")


@pytest.mark.asyncio
async def test_fund_user_rejects_negative_amount(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin cannot top up a wallet by a negative amount"""
    response = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "-50",
            "currency": "ZAR",
            "reason": "trying to withdraw via fund-user",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fund_user_requires_reason(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an admin must give a reason when topping up a wallet"""
    response = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fund_user_unknown_tenant_returns_404(
    async_client: AsyncClient,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify topping up a wallet for an unknown tenant is refused"""
    response = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=admin_auth_header,
        json={
            "tenant_id": str(uuid4()),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "100",
            "currency": "ZAR",
            "reason": "test",
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fund_user_rejects_credit_over_max_balance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
    approver_header: dict[str, str],
) -> None:
    """Verify a top-up that would push a wallet past its maximum balance is refused

    An over-cap fund is rejected by the balance guard at APPLY time (invariant #11).

    Propose succeeds (PENDING); the max-balance breach surfaces on approval and
    nothing lands.
    """
    wallet = await _seed_user_wallet(db_session, test_tenant, test_user)
    db_session.add(
        WalletLimitConfig(tenant_id=test_tenant.id, currency="ZAR", max_balance=Decimal("100"))
    )
    await db_session.commit()

    proposed = await async_client.post(
        "/api/v1/treasury/fund-user",
        headers=admin_auth_header,
        json={
            "tenant_id": str(test_tenant.id),
            "identifier_type": "phone",
            "identifier_value": _user_phone(test_user),
            "amount": "150",
            "currency": "ZAR",
            "reason": "over-cap fund attempt",
        },
    )
    assert proposed.status_code == 201, proposed.text

    approved = await approve_op(
        async_client, str(test_tenant.id), proposed.json()["id"], approver_header
    )
    assert approved.status_code == 409, approved.text
    assert approved.json()["error_code"] == "max_balance_exceeded"

    bal, _ = await derive_balance(db_session, wallet.id)
    assert bal == Decimal("0")
