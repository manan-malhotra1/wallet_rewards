"""Tax config + `calculate_tax` tests (Story 19.4).

Percentage math on fee and commission bases; the inclusive/exclusive flags are
surfaced on the result (they steer the assembler, not the amount); no-config →
zero tax.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxes.schemas import TaxConfigCreateRequest
from app.modules.taxes.service import calculate_tax, create_tax_config
from app.shared.models import Tenant


async def _make_tax(
    session: AsyncSession,
    tenant: Tenant,
    *,
    fee_pct: str = "0",
    commission_pct: str = "0",
    fee_incl: bool = False,
    commission_incl: bool = False,
) -> None:
    await create_tax_config(
        session,
        TaxConfigCreateRequest(
            tenant_id=tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal(fee_pct),
            commission_tax_pct=Decimal(commission_pct),
            fee_tax_inclusive=fee_incl,
            commission_tax_inclusive=commission_incl,
        ),
    )


@pytest.mark.asyncio
async def test_tax_percentage_math(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Tax on fee and commission is rate*base, rounded to 6dp."""
    await _make_tax(db_session, test_tenant, fee_pct="0.15", commission_pct="0.15")
    result = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("2"),
        commission=Decimal("1"),
    )
    assert result.fee_tax == Decimal("0.300000")  # 0.15 * 2
    assert result.commission_tax == Decimal("0.150000")  # 0.15 * 1


@pytest.mark.asyncio
async def test_inclusive_flags_surface_on_result(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """The inclusive/exclusive flags travel back for the assembler to use."""
    await _make_tax(
        db_session,
        test_tenant,
        fee_pct="0.10",
        commission_pct="0.10",
        fee_incl=False,
        commission_incl=True,
    )
    result = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("10"),
        commission=Decimal("10"),
    )
    assert result.fee_tax_inclusive is False
    assert result.commission_tax_inclusive is True
    assert result.fee_tax == Decimal("1.000000")
    assert result.commission_tax == Decimal("1.000000")


@pytest.mark.asyncio
async def test_no_config_means_zero_tax(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """No tax config → zero tax with exclusive (default) flags."""
    result = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("50"),
        commission=Decimal("50"),
    )
    assert result.fee_tax == Decimal("0")
    assert result.commission_tax == Decimal("0")
    assert result.fee_tax_inclusive is False
    assert result.commission_tax_inclusive is False
