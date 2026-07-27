"""Transaction limits — per customer type.

Confirms the resolution order at enforcement: an exact-`user_type` config beats
the `user_type IS NULL` default, the default covers every other type, and no
config at all is a graceful pass-through. Also checks the NULLS NOT DISTINCT
uniqueness (a second NULL-default row for the same dims collides).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.limits.schemas import LimitConfigCreateRequest
from app.modules.limits.service import check_limits, create_limit_config
from app.shared.exceptions import AmountAboveMax, AppHTTPException
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant, User


async def _make_user(session: AsyncSession, tenant: Tenant, user_type: str) -> User:
    """Persist a bare user of the given type (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type=user_type)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_limit(
    session: AsyncSession, tenant: Tenant, *, user_type: str | None, max_amount: str
) -> None:
    """Create a p2p/ZAR limit config with only a max_amount cap."""
    await create_limit_config(
        session,
        LimitConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            user_type=user_type,
            max_amount=Decimal(max_amount),
        ),
    )


async def _check(session: AsyncSession, tenant: Tenant, user: User, amount: str) -> None:
    await check_limits(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal(amount),
    )


@pytest.mark.asyncio
async def test_typed_config_beats_default(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify each customer type is held to its own configured limits."""
    await _make_limit(db_session, test_tenant, user_type=None, max_amount="100")
    await _make_limit(db_session, test_tenant, user_type="agent", max_amount="1000")
    agent = await _make_user(db_session, test_tenant, "agent")

    # 500 exceeds the default (100) but is within the agent cap (1000).
    await _check(db_session, test_tenant, agent, "500")
    # 1500 exceeds even the agent cap.
    with pytest.raises(AmountAboveMax):
        await _check(db_session, test_tenant, agent, "1500")


@pytest.mark.asyncio
async def test_untyped_user_falls_back_to_default(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a customer with no type-specific limit falls back to the default limit."""
    await _make_limit(db_session, test_tenant, user_type=None, max_amount="100")
    await _make_limit(db_session, test_tenant, user_type="agent", max_amount="1000")
    consumer = await _make_user(db_session, test_tenant, "consumer")

    with pytest.raises(AmountAboveMax):
        await _check(db_session, test_tenant, consumer, "500")  # > default 100


@pytest.mark.asyncio
async def test_default_covers_every_type(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the default limit applies to every customer type without its own limit."""
    await _make_limit(db_session, test_tenant, user_type=None, max_amount="100")
    merchant = await _make_user(db_session, test_tenant, "merchant")
    with pytest.raises(AmountAboveMax):
        await _check(db_session, test_tenant, merchant, "500")


@pytest.mark.asyncio
async def test_no_config_is_passthrough(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a transaction is allowed through when no limit is configured for it."""
    consumer = await _make_user(db_session, test_tenant, "consumer")
    await _check(db_session, test_tenant, consumer, "999999")


@pytest.mark.asyncio
async def test_second_default_row_collides(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a duplicate default limit for the same transaction cannot be created."""
    await _make_limit(db_session, test_tenant, user_type=None, max_amount="100")
    # A typed row for the same dims coexists (different user_type).
    await _make_limit(db_session, test_tenant, user_type="agent", max_amount="1000")
    # A second NULL-default for the same dims collides.
    with pytest.raises(AppHTTPException) as exc:
        await _make_limit(db_session, test_tenant, user_type=None, max_amount="200")
    assert exc.value.status_code == 409
