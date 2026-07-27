"""Fee tier boundaries on a transfer.

The band range `[amount_from, amount_to]` is INCLUSIVE on BOTH ends: a
transaction whose amount equals a band's `amount_to` must resolve to that band
and be charged its fee. The UI shows "401.00-500.00" and reads it as inclusive,
so a P2P of exactly 500 under a 401-500 band must charge the fee — it previously
fell into a gap (exclusive upper bound) and charged nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import (
    _find_pricing_config,
    calculate_fee,
    create_pricing_config,
)
from app.shared.exceptions import PricingConfigMissing
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant, User
from app.shared.utils.user_types import resolve_user_type


async def _make_user(session: AsyncSession, tenant: Tenant) -> User:
    """Persist a bare consumer (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type="consumer")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_band(
    session: AsyncSession,
    tenant: Tenant,
    *,
    amount_from: str,
    amount_to: str,
    fixed_fee: str,
) -> None:
    """Create a p2p/ZAR pricing band for the default (NULL) user type."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            user_type=None,
            amount_from=Decimal(amount_from),
            amount_to=Decimal(amount_to),
            fixed_fee=Decimal(fixed_fee),
        ),
    )


async def _seed_three_bands(session: AsyncSession, tenant: Tenant) -> None:
    """Bands 1-200 (fee 1), 201-400 (fee 2), 401-500 (fee 3)."""
    await _make_band(session, tenant, amount_from="1", amount_to="200", fixed_fee="1")
    await _make_band(session, tenant, amount_from="201", amount_to="400", fixed_fee="2")
    await _make_band(session, tenant, amount_from="401", amount_to="500", fixed_fee="3")


async def _resolve(
    session: AsyncSession, tenant: Tenant, user: User, amount: str
) -> Decimal | None:
    """Return the resolved band's fixed_fee, or None if no band matches."""
    user_type = await resolve_user_type(session, tenant.id, user.id)
    config = await _find_pricing_config(
        session,
        tenant_id=tenant.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user_type=user_type,
        amount=Decimal(amount),
    )
    return None if config is None else Decimal(str(config.fixed_fee))


@pytest.mark.asyncio
async def test_upper_bound_is_inclusive(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the correct fee tier applies right at a tier boundary amount."""
    await _seed_three_bands(db_session, test_tenant)
    user = await _make_user(db_session, test_tenant)

    # Interior + upper-boundary amounts all resolve to the correct band.
    assert await _resolve(db_session, test_tenant, user, "200") == Decimal("1")  # was a gap
    assert await _resolve(db_session, test_tenant, user, "201") == Decimal("2")
    assert await _resolve(db_session, test_tenant, user, "400") == Decimal("2")  # was a gap
    assert await _resolve(db_session, test_tenant, user, "401") == Decimal("3")
    assert await _resolve(db_session, test_tenant, user, "500") == Decimal("3")  # was a gap


@pytest.mark.asyncio
async def test_above_top_band_resolves_none(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify no fee tier applies to an amount above the highest configured tier."""
    await _seed_three_bands(db_session, test_tenant)
    user = await _make_user(db_session, test_tenant)
    assert await _resolve(db_session, test_tenant, user, "501") is None


@pytest.mark.asyncio
async def test_upper_boundary_fee_is_applied(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a transfer at the exact top of a fee tier is charged that tier's fee."""
    await _seed_three_bands(db_session, test_tenant)
    user = await _make_user(db_session, test_tenant)

    fee = await calculate_fee(
        db_session,
        tenant_id=test_tenant.id,
        user_id=user.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("500"),
    )
    assert fee == Decimal("3.000000")


@pytest.mark.asyncio
async def test_above_top_band_raises_missing(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a transfer above every configured fee tier is blocked rather than charged nothing."""
    await _seed_three_bands(db_session, test_tenant)
    user = await _make_user(db_session, test_tenant)
    with pytest.raises(PricingConfigMissing):
        await calculate_fee(
            db_session,
            tenant_id=test_tenant.id,
            user_id=user.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount=Decimal("501"),
        )
