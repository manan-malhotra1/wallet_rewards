"""The commission_wallet account type exists and is persistable.

Guards the CHECK constraint extension in migration 0066: a commission_wallet
row must insert cleanly, and the type must stay DISTINCT from the tenant-level
`commission` pool it is easily confused with (spec 2026-08-26, D1).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION,
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPES,
    Account,
    Tenant,
    User,
)


def test_commission_wallet_is_a_distinct_account_type() -> None:
    """The wallet and the funding pool are two different account types."""
    assert ACCOUNT_TYPE_COMMISSION_WALLET == "commission_wallet"
    assert ACCOUNT_TYPE_COMMISSION_WALLET in ACCOUNT_TYPES
    assert ACCOUNT_TYPE_COMMISSION_WALLET != ACCOUNT_TYPE_COMMISSION


@pytest.mark.asyncio
async def test_commission_wallet_row_persists(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A user-owned commission wallet inserts past ck_accounts_type."""
    account = Account(
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
        currency="ZAR",
    )
    db_session.add(account)
    await db_session.commit()

    found = (
        await db_session.execute(
            select(Account).where(
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalar_one()
    assert found.currency == "ZAR"


@pytest.mark.asyncio
async def test_tenant_commission_flag_defaults_false(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Existing tenants stay opted out until explicitly created with the flag."""
    await db_session.refresh(test_tenant)
    assert test_tenant.commission_wallet_enabled is False
