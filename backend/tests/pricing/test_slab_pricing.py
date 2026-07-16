"""Amount-slab pricing tests (Story 19.2).

The amount picks the band whose `[amount_from, amount_to]` contains it; a
specific band beats the NULL-band default; a typed row beats the NULL-type
default; and a single NULL-band config keeps working (back-compat).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import calculate_fee, create_pricing_config
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant, User


async def _make_user(session: AsyncSession, tenant: Tenant, user_type: str) -> User:
    """Persist a bare user of the given type (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type=user_type)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_band(
    session: AsyncSession,
    tenant: Tenant,
    *,
    user_type: str | None,
    amount_from: str | None,
    amount_to: str | None,
    fixed_fee: str,
) -> None:
    """Create a p2p/ZAR pricing config for one amount band."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            user_type=user_type,
            amount_from=Decimal(amount_from) if amount_from is not None else None,
            amount_to=Decimal(amount_to) if amount_to is not None else None,
            fixed_fee=Decimal(fixed_fee),
        ),
    )


async def _fee(session: AsyncSession, tenant: Tenant, user: User, amount: str) -> Decimal:
    return await calculate_fee(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal(amount),
    )


@pytest.mark.asyncio
async def test_amount_selects_the_right_band(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Two bands [0,99] fee 2 and [100,None] fee 9 — amount picks the band.

    Bounds are inclusive on both ends, so the bands must not share the 100
    endpoint; the closed band ends at 99 and the open band starts at 100.
    """
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from="0", amount_to="99", fixed_fee="2"
    )
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from="100", amount_to=None, fixed_fee="9"
    )
    consumer = await _make_user(db_session, test_tenant, "consumer")

    assert await _fee(db_session, test_tenant, consumer, "50") == Decimal("2.000000")
    assert await _fee(db_session, test_tenant, consumer, "99") == Decimal("2.000000")  # upper incl
    assert await _fee(db_session, test_tenant, consumer, "100") == Decimal("9.000000")  # upper open
    assert await _fee(db_session, test_tenant, consumer, "500") == Decimal("9.000000")


@pytest.mark.asyncio
async def test_specific_band_beats_null_band_default(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A NULL-band default (fee 5) is overridden by a [0,100) band (fee 1)."""
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from=None, amount_to=None, fixed_fee="5"
    )
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from="0", amount_to="100", fixed_fee="1"
    )
    consumer = await _make_user(db_session, test_tenant, "consumer")

    assert await _fee(db_session, test_tenant, consumer, "50") == Decimal("1.000000")  # in band
    assert await _fee(db_session, test_tenant, consumer, "500") == Decimal("5.000000")  # falls back


@pytest.mark.asyncio
async def test_typed_band_beats_default_band(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """For the same [0,100) band, a merchant-typed row (fee 1) beats the default (fee 4)."""
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from="0", amount_to="100", fixed_fee="4"
    )
    await _make_band(
        db_session,
        test_tenant,
        user_type="merchant",
        amount_from="0",
        amount_to="100",
        fixed_fee="1",
    )
    merchant = await _make_user(db_session, test_tenant, "merchant")
    consumer = await _make_user(db_session, test_tenant, "consumer")

    assert await _fee(db_session, test_tenant, merchant, "50") == Decimal("1.000000")
    assert await _fee(db_session, test_tenant, consumer, "50") == Decimal("4.000000")


@pytest.mark.asyncio
async def test_null_band_back_compat(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """A single NULL-band config (the pre-slab shape) applies to every amount."""
    await _make_band(
        db_session, test_tenant, user_type=None, amount_from=None, amount_to=None, fixed_fee="3"
    )
    consumer = await _make_user(db_session, test_tenant, "consumer")

    assert await _fee(db_session, test_tenant, consumer, "1") == Decimal("3.000000")
    assert await _fee(db_session, test_tenant, consumer, "999999") == Decimal("3.000000")
