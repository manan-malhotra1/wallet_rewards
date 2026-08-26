"""Type change into an eligible category provisions; out of it retains (spec §6.3).

Retention on the way out is not laziness: the ledger is append-only and the
balance may be non-zero, so the wallet must survive to stay disbursable.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.provisioning import provision_user_accounts
from app.modules.identity.schemas import ChangeUserTypeRequest
from app.modules.identity.service import change_user_type
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
    User,
)


async def _has_commission_wallet(session: AsyncSession, user: User) -> bool:
    """Does this user hold any commission wallet?"""
    row = (
        await session.execute(
            select(Account).where(
                Account.user_id == user.id,
                Account.account_type == ACCOUNT_TYPE_COMMISSION_WALLET,
            )
        )
    ).scalars().first()
    return row is not None


async def _flag_on_with_zar(session: AsyncSession, tenant: Tenant) -> None:
    """Turn the tenant flag on and guarantee a ZAR instrument."""
    tenant.commission_wallet_enabled = True
    existing = (
        await session.execute(
            select(Instrument).where(
                Instrument.tenant_id == tenant.id, Instrument.code == "ZAR"
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Instrument(
                tenant_id=tenant.id,
                code="ZAR",
                symbol="R",
                display_name="Rand",
                account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_promotion_into_retail_provisions(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    """A consumer promoted to super_agent earns a commission wallet."""
    await _flag_on_with_zar(db_session, test_tenant)
    test_user.user_type = "consumer"
    await db_session.commit()
    assert not await _has_commission_wallet(db_session, test_user)

    await change_user_type(
        db_session,
        user_id=test_user.id,
        tenant_id=test_tenant.id,
        request=ChangeUserTypeRequest(new_type="super_agent", reason="promotion"),
        admin=admin_principal,
    )

    assert await _has_commission_wallet(db_session, test_user)


@pytest.mark.asyncio
async def test_demotion_out_of_retail_retains_the_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User, admin_principal
) -> None:
    """The wallet survives demotion — its balance must stay disbursable."""
    await _flag_on_with_zar(db_session, test_tenant)
    test_user.user_type = "super_agent"
    await db_session.commit()
    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()
    assert await _has_commission_wallet(db_session, test_user)

    await change_user_type(
        db_session,
        user_id=test_user.id,
        tenant_id=test_tenant.id,
        request=ChangeUserTypeRequest(new_type="consumer", reason="demotion"),
        admin=admin_principal,
    )

    assert await _has_commission_wallet(db_session, test_user)
