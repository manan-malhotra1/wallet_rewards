"""Destination and parent-rate columns persist with the right defaults (spec §4.3).

The DB defaults exist so migration 0067 backfills existing rows to TODAY'S
behaviour: main wallet, no parent commission. Nothing may reprice on deploy (D18).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import CommissionConfig, Tenant


@pytest.mark.asyncio
async def test_defaults_reproduce_todays_behaviour(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A row written without the new columns behaves exactly as before."""
    config = CommissionConfig(
        tenant_id=test_tenant.id,
        transaction_type="cash_in",
        currency="ZAR",
        user_type="agent",
        fixed_commission=Decimal("1"),
        variable_commission_pct=Decimal("0.01"),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    assert config.payout_destination == "main_wallet"
    assert Decimal(str(config.parent_fixed_commission)) == Decimal("0")
    assert Decimal(str(config.parent_variable_commission_pct)) == Decimal("0")
    assert config.parent_commission_cap is None


@pytest.mark.asyncio
async def test_parent_rates_persist(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """All four new columns round-trip."""
    config = CommissionConfig(
        tenant_id=test_tenant.id,
        transaction_type="cash_in",
        currency="ZAR",
        user_type="agent",
        fixed_commission=Decimal("1"),
        variable_commission_pct=Decimal("0.01"),
        payout_destination="commission_wallet",
        parent_fixed_commission=Decimal("0.5"),
        parent_variable_commission_pct=Decimal("0.005"),
        parent_commission_cap=Decimal("20"),
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)

    assert config.payout_destination == "commission_wallet"
    assert Decimal(str(config.parent_variable_commission_pct)) == Decimal("0.005")
    assert Decimal(str(config.parent_commission_cap)) == Decimal("20")
