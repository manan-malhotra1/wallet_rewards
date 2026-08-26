"""Adding a currency later backfills commission wallets for existing users (spec §6.2).

The business case verbatim: "if an instrument is later added, for example INR,
the older agents and the older retail and business users will also get a
commission wallet, just as we give the new currency wallet to all users."
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _held(session: AsyncSession, user: User, currency: str) -> set[str]:
    """Account types this user holds in one currency."""
    rows = (
        await session.execute(
            select(Account).where(
                Account.user_id == user.id, Account.currency == currency
            )
        )
    ).scalars().all()
    return {a.account_type for a in rows}


async def _create_inr(client: AsyncClient, tenant: Tenant, headers: dict[str, str]):
    """Create an INR financial instrument through the admin API."""
    return await client.post(
        "/api/v1/instruments",
        headers=headers,
        json={
            "tenant_id": str(tenant.id),
            "code": "INR",
            "symbol": "R",
            "display_name": "Rupee",
            "account_type": "financial_wallet",
            "assign_to_existing_users": True,
        },
    )


@pytest.mark.asyncio
async def test_new_currency_backfills_both_wallets_for_an_agent(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """An existing agent gets both an INR main wallet and an INR commission wallet."""
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "agent"
    await db_session.commit()

    resp = await _create_inr(async_client, test_tenant, admin_auth_header)
    assert resp.status_code == 201, resp.text

    assert await _held(db_session, test_user, "INR") == {
        ACCOUNT_TYPE_FINANCIAL_WALLET,
        ACCOUNT_TYPE_COMMISSION_WALLET,
    }


@pytest.mark.asyncio
async def test_new_currency_gives_a_consumer_only_the_main_wallet(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Consumers are excluded from the second pass."""
    test_tenant.commission_wallet_enabled = True
    test_user.user_type = "consumer"
    await db_session.commit()

    resp = await _create_inr(async_client, test_tenant, admin_auth_header)
    assert resp.status_code == 201, resp.text

    assert await _held(db_session, test_user, "INR") == {ACCOUNT_TYPE_FINANCIAL_WALLET}


@pytest.mark.asyncio
async def test_flag_off_tenant_backfills_main_wallet_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    admin_auth_header: dict[str, str],
) -> None:
    """Existing behaviour is untouched for tenants that never opted in."""
    test_tenant.commission_wallet_enabled = False
    test_user.user_type = "agent"
    await db_session.commit()

    resp = await _create_inr(async_client, test_tenant, admin_auth_header)
    assert resp.status_code == 201, resp.text

    assert await _held(db_session, test_user, "INR") == {ACCOUNT_TYPE_FINANCIAL_WALLET}
