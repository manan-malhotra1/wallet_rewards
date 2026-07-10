"""Tests for POST /api/v1/treasury/fund-user (admin top-up)."""

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
) -> None:
    """Funding R 500 lands a top-up txn + bumps the user's wallet balance."""
    wallet = await _seed_user_wallet(db_session, test_tenant, test_user)

    response = await async_client.post(
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
    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(body["new_balance"]) == Decimal("500")
    assert body["user_id"] == str(test_user.id)
    assert body["currency"] == "ZAR"

    # Re-derive directly to be sure the response wasn't lying.
    bal, _ = await derive_balance(db_session, wallet.id)
    assert bal == Decimal("500")


@pytest.mark.asyncio
async def test_fund_user_rejects_negative_amount(
    async_client: AsyncClient,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Pydantic gt=0 → negative amount → 422."""
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
    """Empty `reason` → 422 — the audit row needs context."""
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
    """Unknown tenant_id → 404."""
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
) -> None:
    """An operator fund that would breach the wallet's max_balance is rejected by
    the balance guard (invariant #11): fund-user credits a financial_wallet, so it
    is cap-checked under the wallet lock like every other credit. Nothing lands."""
    wallet = await _seed_user_wallet(db_session, test_tenant, test_user)
    db_session.add(
        WalletLimitConfig(tenant_id=test_tenant.id, currency="ZAR", max_balance=Decimal("100"))
    )
    await db_session.commit()

    response = await async_client.post(
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
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "max_balance_exceeded"

    bal, _ = await derive_balance(db_session, wallet.id)
    assert bal == Decimal("0")
