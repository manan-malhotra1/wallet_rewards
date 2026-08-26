"""Parent commission is taxed on the same axis, computed PER LEG (D11).

Per-leg rather than on the combined total, because rounding a combined figure
and splitting it afterwards does not reconcile against two separate ledger legs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxes.service import calculate_tax
from app.shared.models import TaxConfig, Tenant


async def _tax_config(session: AsyncSession, tenant: Tenant, *, inclusive: bool = False):
    """A 15% commission tax config for ZAR."""
    session.add(
        TaxConfig(
            tenant_id=tenant.id,
            currency="ZAR",
            fee_tax_pct=Decimal("0"),
            commission_tax_pct=Decimal("0.15"),
            commission_tax_inclusive=inclusive,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_parent_commission_is_taxed_at_the_same_rate(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """R10 child and R5 parent at 15% → R1.50 and R0.75, each rounded alone."""
    await _tax_config(db_session, test_tenant)

    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
        parent_commission=Decimal("5"),
    )

    assert tax.commission_tax == Decimal("1.500000")
    assert tax.parent_commission_tax == Decimal("0.750000")
    assert tax.commission_tax_inclusive is False


@pytest.mark.asyncio
async def test_zero_parent_commission_is_taxed_zero(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A skipped parent leg contributes no tax."""
    await _tax_config(db_session, test_tenant)

    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
        parent_commission=Decimal("0"),
    )
    assert tax.parent_commission_tax == Decimal("0")


@pytest.mark.asyncio
async def test_omitting_parent_commission_is_backward_compatible(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Pre-parent callers keep working — the parameter defaults to zero."""
    await _tax_config(db_session, test_tenant)

    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
    )
    assert tax.commission_tax == Decimal("1.500000")
    assert tax.parent_commission_tax == Decimal("0")


@pytest.mark.asyncio
async def test_missing_tax_config_yields_zero_parent_tax(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """No config → all-zero computation, including the new field."""
    tax = await calculate_tax(
        db_session,
        tenant_id=test_tenant.id,
        currency="ZAR",
        fee=Decimal("0"),
        commission=Decimal("10"),
        parent_commission=Decimal("5"),
    )
    assert tax.parent_commission_tax == Decimal("0")
