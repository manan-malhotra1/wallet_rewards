"""Fee calculation from pricing configuration."""

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
async def test_missing_config_raises(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a transaction is blocked when no price is configured for it."""
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
async def test_fixed_fee_only(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a flat fee is charged regardless of the transfer amount."""
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
async def test_variable_fee_capped(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a percentage fee never exceeds its configured cap."""
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
async def test_zero_fee_config_returns_zero(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify an explicitly configured zero fee charges nothing."""
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
    """Verify collected fees are gathered into one account rather than duplicated."""
    first = await get_or_create_system_fee_account(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    second = await get_or_create_system_fee_account(
        db_session, tenant_id=test_tenant.id, currency="ZAR"
    )
    assert first.id == second.id
    assert first.account_type == ACCOUNT_TYPE_SYSTEM_FEE_COLLECTED
