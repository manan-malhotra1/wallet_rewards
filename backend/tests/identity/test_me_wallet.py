"""Tests for GET /api/v1/identity/me/wallet (user-facing wallet view).

The mobile-simulator and the eventual real mobile app call this endpoint
to render the user's accounts + recent transactions. Auth is the user's
session token (PIN login), NOT admin.

Covers:
  - Happy path: authenticated user gets their own accounts + recent txns
  - 401: no Authorization header
  - 401: bad / expired token
  - No data leak: a second user's accounts never appear in the response
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    Tenant,
    User,
)


@pytest.mark.asyncio
async def test_me_wallet_returns_caller_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Auth as test_user → response carries that user's id + accounts."""
    # Give the user a ZAR financial wallet so accounts is non-empty.
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency="PTS",
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(test_user.id)
    assert body["tenant_id"] == str(test_user.tenant_id)
    account_types = {a["account_type"] for a in body["accounts"]}
    assert ACCOUNT_TYPE_FINANCIAL_WALLET in account_types
    assert ACCOUNT_TYPE_POINTS in account_types


@pytest.mark.asyncio
async def test_me_wallet_no_token_is_401(async_client: AsyncClient) -> None:
    """Missing Authorization header → 401."""
    response = await async_client.get("/api/v1/identity/me/wallet")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_wallet_bad_token_is_401(async_client: AsyncClient) -> None:
    """Unknown bearer token → 401."""
    response = await async_client.get(
        "/api/v1/identity/me/wallet",
        headers={"Authorization": "Bearer not-a-real-session-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_wallet_does_not_leak_other_users_accounts(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    alice_auth_header: dict[str, str],
) -> None:
    """Another user's accounts in the same tenant must NOT appear."""
    other = User(tenant_id=test_tenant.id)
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=other.id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    response = await async_client.get("/api/v1/identity/me/wallet", headers=alice_auth_header)
    assert response.status_code == 200
    body = response.json()
    # test_user has no accounts of its own in this test — the only account
    # in the tenant belongs to `other`. The response MUST return zero
    # accounts, not other's account.
    assert body["user_id"] == str(test_user.id)
    assert body["accounts"] == []
