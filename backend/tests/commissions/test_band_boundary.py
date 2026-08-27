"""Commission tier boundaries.

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
            # Required since spec D8: zero is a decision, not an omission.
            # These tests are about the CHILD leg, so the parent earns nothing.
            parent_fixed_commission=Decimal("0"),
            parent_variable_commission_pct=Decimal("0"),
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
    """The agent's OWN commission for one amount.

    `calculate_commission` returns a CommissionOutcome (both legs plus the
    destination) since the commission-wallet edition; these band tests are only
    about the child leg's band resolution, so they read `self_amount`.
    """
    outcome = await calculate_commission(
        session,
        tenant_id=tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal(amount),
    )
    return outcome.self_amount


@pytest.mark.asyncio
async def test_commission_upper_bound_is_inclusive(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify the correct commission tier applies right at a tier boundary amount."""
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
