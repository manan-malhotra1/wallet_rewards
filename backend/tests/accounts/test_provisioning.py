"""provision_user_accounts — the single source of "which wallets should this user hold".

Called from user create, instrument create and type change (spec §6). Every
caller relies on it being idempotent, so re-running must never duplicate a row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.provisioning import provision_user_accounts
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    Account,
    Instrument,
    Tenant,
    User,
)


async def _types_held(session: AsyncSession, user: User) -> set[tuple[str, str]]:
    """Every (account_type, currency) pair this user holds."""
    rows = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    return {(a.account_type, a.currency) for a in rows}


async def _add_instrument(
    session: AsyncSession, tenant: Tenant, code: str, account_type: str
) -> None:
    """Add one instrument, skipping if the tenant seed already created it."""
    existing = (
        await session.execute(
            select(Instrument).where(
                Instrument.tenant_id == tenant.id, Instrument.code == code
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(
        Instrument(
            tenant_id=tenant.id,
            code=code,
            symbol=code,
            display_name=code,
            account_type=account_type,
        )
    )
    await session.commit()


async def _setup(
    session: AsyncSession, tenant: Tenant, user: User, *, flag: bool, user_type: str
) -> None:
    """Put the tenant flag and the user's type into a known state."""
    tenant.commission_wallet_enabled = flag
    user.user_type = user_type
    await session.commit()


@pytest.mark.asyncio
async def test_consumer_gets_main_wallet_only(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Every user gets a main wallet, consumers included (D12) — but no commission one."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="consumer")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    assert (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR") in held
    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR") not in held


@pytest.mark.asyncio
async def test_agent_on_flag_on_tenant_gets_both(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """A Retail-category user on a flag-on tenant holds both wallets."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="agent")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    assert (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR") in held
    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR") in held


@pytest.mark.asyncio
async def test_merchant_is_eligible_too(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Business category is eligible, not only Retail (D4)."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="merchant")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR") in await _types_held(
        db_session, test_user
    )


@pytest.mark.asyncio
async def test_agent_on_flag_off_tenant_gets_main_only(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """The tenant flag gates it, not just the category."""
    await _setup(db_session, test_tenant, test_user, flag=False, user_type="agent")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    assert (ACCOUNT_TYPE_FINANCIAL_WALLET, "ZAR") in held
    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "ZAR") not in held


@pytest.mark.asyncio
async def test_points_instrument_provisions_no_commission_wallet(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Financial currencies only — a PTS instrument yields no commission wallet."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="agent")
    await _add_instrument(db_session, test_tenant, "PTS", ACCOUNT_TYPE_POINTS)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    assert (ACCOUNT_TYPE_COMMISSION_WALLET, "PTS") not in held


@pytest.mark.asyncio
async def test_multi_currency(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """Both wallet kinds appear once per active financial currency."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="agent")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)
    await _add_instrument(db_session, test_tenant, "INR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    held = await _types_held(db_session, test_user)
    for currency in ("ZAR", "INR"):
        assert (ACCOUNT_TYPE_FINANCIAL_WALLET, currency) in held
        assert (ACCOUNT_TYPE_COMMISSION_WALLET, currency) in held


@pytest.mark.asyncio
async def test_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant, test_user: User
) -> None:
    """All three callers re-invoke this freely; a second run must add nothing."""
    await _setup(db_session, test_tenant, test_user, flag=True, user_type="agent")
    await _add_instrument(db_session, test_tenant, "ZAR", ACCOUNT_TYPE_FINANCIAL_WALLET)

    first = await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()
    second = await provision_user_accounts(
        db_session, tenant_id=test_tenant.id, user_id=test_user.id
    )
    await db_session.commit()

    assert first > 0
    assert second == 0


@pytest.mark.asyncio
async def test_unknown_user_is_a_no_op(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A user id from another tenant provisions nothing rather than raising."""
    from uuid import uuid4

    assert (
        await provision_user_accounts(
            db_session, tenant_id=test_tenant.id, user_id=uuid4()
        )
        == 0
    )
