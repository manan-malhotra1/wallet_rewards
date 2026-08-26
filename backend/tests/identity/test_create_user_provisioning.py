"""Users get their wallets at creation (spec D12).

Before this change NO creation path provisioned a financial wallet: a user
created after the last instrument existed held no account at all and 404'd
with AccountNotFound on their first cash-in. This test locks that shut.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.schemas import CreateUserRequest, IdentifierIn
from app.modules.identity.service import create_user
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Instrument,
    Tenant,
)

_PHONE = iter(f"+2782555{n:04d}" for n in range(1000, 9999))


async def _ensure_zar(session: AsyncSession, tenant: Tenant) -> None:
    """Guarantee the tenant has a live ZAR financial instrument."""
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


async def _types_held(session: AsyncSession, user_id: UUID) -> set[str]:
    """Account types the user holds."""
    rows = (
        await session.execute(select(Account).where(Account.user_id == user_id))
    ).scalars().all()
    return {a.account_type for a in rows}


def _request(tenant: Tenant, user_type: str) -> CreateUserRequest:
    """A minimal create body with a unique phone."""
    return CreateUserRequest(
        tenant_id=tenant.id,
        user_type=user_type,
        identifiers=[
            IdentifierIn(identifier_type="phone", identifier_value=next(_PHONE))
        ],
    )


@pytest.mark.asyncio
async def test_consumer_gets_a_main_wallet(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role
) -> None:
    """Closes the latent gap — every user is transactable the moment they exist."""
    await _ensure_zar(db_session, test_tenant)
    user = await create_user(db_session, _request(test_tenant, "consumer"))
    assert ACCOUNT_TYPE_FINANCIAL_WALLET in await _types_held(db_session, user.id)


@pytest.mark.asyncio
async def test_agent_on_flag_on_tenant_gets_both(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role
) -> None:
    """A new agent is ready to accrue commission immediately."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _ensure_zar(db_session, test_tenant)

    user = await create_user(db_session, _request(test_tenant, "agent"))

    held = await _types_held(db_session, user.id)
    assert ACCOUNT_TYPE_FINANCIAL_WALLET in held
    assert ACCOUNT_TYPE_COMMISSION_WALLET in held


@pytest.mark.asyncio
async def test_agent_on_flag_off_tenant_gets_main_only(
    db_session: AsyncSession, test_tenant: Tenant, default_user_role
) -> None:
    """Tenants that never opted in are completely unaffected by this feature."""
    test_tenant.commission_wallet_enabled = False
    await db_session.commit()
    await _ensure_zar(db_session, test_tenant)

    user = await create_user(db_session, _request(test_tenant, "agent"))

    held = await _types_held(db_session, user.id)
    assert ACCOUNT_TYPE_FINANCIAL_WALLET in held
    assert ACCOUNT_TYPE_COMMISSION_WALLET not in held
