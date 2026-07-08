"""Precedence tests for type-aware pricing (Epic 16).

An exact-`user_type` fee config wins over the `user_type IS NULL` default in
quote resolution; the default covers every other type; a missing config still
raises PricingConfigMissing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import calculate_fee, create_pricing_config
from app.shared.exceptions import PricingConfigMissing
from app.shared.models import ACCOUNT_TYPE_FINANCIAL_WALLET, Tenant, User


async def _make_user(session: AsyncSession, tenant: Tenant, user_type: str) -> User:
    """Persist a bare user of the given type (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type=user_type)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_pricing(
    session: AsyncSession, tenant: Tenant, *, user_type: str | None, fixed_fee: str
) -> None:
    """Create a p2p/ZAR pricing config with a fixed fee only."""
    await create_pricing_config(
        session,
        PricingConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            user_type=user_type,
            fixed_fee=Decimal(fixed_fee),
        ),
    )


async def _fee(session: AsyncSession, tenant: Tenant, user: User) -> Decimal:
    return await calculate_fee(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("100"),
    )


@pytest.mark.asyncio
async def test_typed_fee_beats_default(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """A merchant's fee (1) wins over the NULL default (5); a consumer gets 5."""
    await _make_pricing(db_session, test_tenant, user_type=None, fixed_fee="5")
    await _make_pricing(db_session, test_tenant, user_type="merchant", fixed_fee="1")
    merchant = await _make_user(db_session, test_tenant, "merchant")
    consumer = await _make_user(db_session, test_tenant, "consumer")

    assert await _fee(db_session, test_tenant, merchant) == Decimal("1.000000")
    assert await _fee(db_session, test_tenant, consumer) == Decimal("5.000000")


@pytest.mark.asyncio
async def test_default_applies_when_no_typed(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """An agent with no agent-specific fee resolves to the NULL default."""
    await _make_pricing(db_session, test_tenant, user_type=None, fixed_fee="5")
    agent = await _make_user(db_session, test_tenant, "agent")
    assert await _fee(db_session, test_tenant, agent) == Decimal("5.000000")


@pytest.mark.asyncio
async def test_missing_config_raises(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """No config for the slot still raises PricingConfigMissing (Pay-PRD-0420)."""
    consumer = await _make_user(db_session, test_tenant, "consumer")
    with pytest.raises(PricingConfigMissing):
        await _fee(db_session, test_tenant, consumer)
