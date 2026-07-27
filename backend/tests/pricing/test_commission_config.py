"""Operator commission calculation.

Fixed + variable + cap math; typed-vs-default precedence; amount-band selection;
and the no-config → Decimal("0") rule (commission is optional, unlike a fee).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.schemas import CommissionConfigCreateRequest
from app.modules.commissions.service import calculate_commission, create_commission_config
from app.shared.models import Tenant, User


async def _make_agent(session: AsyncSession, tenant: Tenant, user_type: str = "agent") -> User:
    """Persist a bare user of the given type (enough for type resolution)."""
    user = User(tenant_id=tenant.id, user_type=user_type)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_config(
    session: AsyncSession,
    tenant: Tenant,
    *,
    user_type: str | None = None,
    amount_from: str | None = None,
    amount_to: str | None = None,
    fixed: str = "0",
    variable: str = "0",
    cap: str | None = None,
) -> None:
    await create_commission_config(
        session,
        CommissionConfigCreateRequest(
            tenant_id=tenant.id,
            transaction_type="cash_in",
            currency="ZAR",
            user_type=user_type,
            amount_from=Decimal(amount_from) if amount_from is not None else None,
            amount_to=Decimal(amount_to) if amount_to is not None else None,
            fixed_commission=Decimal(fixed),
            variable_commission_pct=Decimal(variable),
            commission_cap=Decimal(cap) if cap is not None else None,
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
async def test_fixed_plus_variable_with_cap(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the operator commission adds a fixed amount to a capped percentage."""
    await _make_config(db_session, test_tenant, fixed="1", variable="0.05", cap="10")
    agent = await _make_agent(db_session, test_tenant)

    # 1 + min(0.05*100, 10) = 1 + 5 = 6
    assert await _commission(db_session, test_tenant, agent, "100") == Decimal("6.000000")
    # 1 + min(0.05*1000, 10) = 1 + 10 (capped) = 11
    assert await _commission(db_session, test_tenant, agent, "1000") == Decimal("11.000000")


@pytest.mark.asyncio
async def test_typed_beats_default(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify an operator type with its own commission rate is paid that rate, not the default."""
    await _make_config(db_session, test_tenant, user_type=None, fixed="5")
    await _make_config(db_session, test_tenant, user_type="agent", fixed="2")
    agent = await _make_agent(db_session, test_tenant, "agent")
    super_agent = await _make_agent(db_session, test_tenant, "super_agent")

    assert await _commission(db_session, test_tenant, agent, "100") == Decimal("2.000000")
    assert await _commission(db_session, test_tenant, super_agent, "100") == Decimal("5.000000")


@pytest.mark.asyncio
async def test_amount_band_selection(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify the commission for the transaction amount comes from the matching amount tier."""
    await _make_config(db_session, test_tenant, amount_from="0", amount_to="100", fixed="1")
    await _make_config(db_session, test_tenant, amount_from="100", amount_to=None, fixed="3")
    agent = await _make_agent(db_session, test_tenant)

    assert await _commission(db_session, test_tenant, agent, "50") == Decimal("1.000000")
    assert await _commission(db_session, test_tenant, agent, "250") == Decimal("3.000000")


@pytest.mark.asyncio
async def test_no_config_means_zero(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify no operator commission is recorded when none is configured."""
    agent = await _make_agent(db_session, test_tenant)
    assert await _commission(db_session, test_tenant, agent, "100") == Decimal("0")
