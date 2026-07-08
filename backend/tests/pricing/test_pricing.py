"""Tests for the pricing service (Phase G.3)."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.schemas import PricingConfigCreateRequest
from app.modules.pricing.service import (
    calculate_fee,
    create_pricing_config,
    get_or_create_system_fee_account,
)
from app.shared.exceptions import PricingConfigMissing
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED,
    Tenant,
)


@pytest.mark.asyncio
async def test_missing_config_raises(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Per Pay-PRD-0420, missing pricing config is an explicit 422 — not a
    silent zero-fee fallback."""
    with pytest.raises(PricingConfigMissing):
        await calculate_fee(
            db_session,
            tenant_id=test_tenant.id,
            user_id=uuid4(),
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            amount=Decimal("100"),
        )


@pytest.mark.asyncio
async def test_fixed_fee_only(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """fixed_fee=R 5, no variable → fee = R 5 regardless of amount."""
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("5"),
        ),
    )
    fee = await calculate_fee(
        db_session,
        tenant_id=test_tenant.id,
        user_id=uuid4(),
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("1000"),
    )
    assert fee == Decimal("5.000000")


@pytest.mark.asyncio
async def test_variable_fee_capped(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """2.5% variable + R 50 cap → R 5000 transfer caps at R 50."""
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            variable_fee_pct=Decimal("0.025"),
            fee_cap=Decimal("50"),
        ),
    )
    fee = await calculate_fee(
        db_session,
        tenant_id=test_tenant.id,
        user_id=uuid4(),
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("5000"),
    )
    # 2.5% * 5000 = 125; capped at 50.
    assert fee == Decimal("50.000000")


@pytest.mark.asyncio
async def test_zero_fee_config_returns_zero(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Operators explicitly opting in to zero-fee via the config."""
    await create_pricing_config(
        db_session,
        PricingConfigCreateRequest(
            tenant_id=test_tenant.id,
            transaction_type="p2p",
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency="ZAR",
            fixed_fee=Decimal("0"),
            variable_fee_pct=Decimal("0"),
        ),
    )
    fee = await calculate_fee(
        db_session,
        tenant_id=test_tenant.id,
        user_id=uuid4(),
        transaction_type="p2p",
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        amount=Decimal("100"),
    )
    assert fee == Decimal("0.000000")


@pytest.mark.asyncio
async def test_get_or_create_system_fee_account_idempotent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """First call creates; subsequent calls return the same row."""
    first = await get_or_create_system_fee_account(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    second = await get_or_create_system_fee_account(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    assert first.id == second.id
    assert first.account_type == ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED
