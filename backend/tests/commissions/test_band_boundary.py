"""Commission amount-band upper-bound boundary tests (money-path boundary fix).

Mirrors the pricing boundary fix: a commission band `[amount_from, amount_to]`
is INCLUSIVE on both ends, so an amount equal to a band's `amount_to` resolves
to that band and pays its commission (previously an exclusive upper bound left
the exact boundary amount with no commission).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import calculate_commission, create_commission_config
from app.shared.models import Tenant, User


async def _make_agent(session: AsyncSession, tenant: Tenant) -> User:
    """Persist a bare agent (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type="agent")
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
    fixed: str,
) -> None:
    """Create a cash_in/ZAR commission band for the default (NULL) user type."""
    await create_commission_config(
        session,
        CommissionConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="cash_in",
            currency="ZAR",
            user_type=None,
            amount_from=Decimal(amount_from),
            amount_to=Decimal(amount_to),
            fixed_commission=Decimal(fixed),
            variable_commission_pct=Decimal("0"),
        ),
    )


async def _commission(session: AsyncSession, tenant: Tenant, agent: User, amount: str) -> Decimal:
    return await calculate_commission(
        session,
        tenant_id=tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal(amount),
    )


@pytest.mark.asyncio
async def test_commission_upper_bound_is_inclusive(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """An amount equal to a band's amount_to pays that band's commission."""
    await _make_band(db_session, test_tenant, amount_from="1", amount_to="200", fixed="1")
    await _make_band(db_session, test_tenant, amount_from="201", amount_to="400", fixed="2")
    await _make_band(db_session, test_tenant, amount_from="401", amount_to="500", fixed="3")
    agent = await _make_agent(db_session, test_tenant)

    assert await _commission(db_session, test_tenant, agent, "200") == Decimal("1.000000")
    assert await _commission(db_session, test_tenant, agent, "201") == Decimal("2.000000")
    assert await _commission(db_session, test_tenant, agent, "400") == Decimal("2.000000")
    assert await _commission(db_session, test_tenant, agent, "401") == Decimal("3.000000")
    assert await _commission(db_session, test_tenant, agent, "500") == Decimal("3.000000")
    # Above the top band's upper end (no open band) → no commission.
    assert await _commission(db_session, test_tenant, agent, "501") == Decimal("0")
