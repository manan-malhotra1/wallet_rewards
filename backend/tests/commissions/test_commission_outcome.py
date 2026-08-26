"""calculate_commission returns both legs, the destination and any skip reason.

The parent rate is a percentage of the TRANSACTION AMOUNT (D8), NOT of the
child's commission — the first test asserts on a case where the two differ by
two orders of magnitude, which is what pins that decision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.service import calculate_commission
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    Account,
    CommissionConfig,
    Tenant,
    User,
)


async def _config(session: AsyncSession, tenant: Tenant, **overrides: Any) -> None:
    """A 1% child / 0.5% parent commission-wallet rule for agents."""
    payload: dict[str, Any] = {
        "tenant_id": tenant.id,
        "transaction_type": "cash_in",
        "currency": "ZAR",
        "user_type": "agent",
        "fixed_commission": Decimal("0"),
        "variable_commission_pct": Decimal("0.01"),
        "payout_destination": "commission_wallet",
        "parent_fixed_commission": Decimal("0"),
        "parent_variable_commission_pct": Decimal("0.005"),
    }
    payload.update(overrides)
    session.add(CommissionConfig(**payload))
    await session.commit()


async def _agent_with_parent(
    session: AsyncSession, tenant: Tenant
) -> tuple[User, User]:
    """An agent under a super-agent, both holding ZAR commission wallets."""
    parent = User(tenant_id=tenant.id, user_type="super_agent")
    session.add(parent)
    await session.commit()
    await session.refresh(parent)

    agent = User(tenant_id=tenant.id, user_type="agent", parent_user_id=parent.id)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    for user in (agent, parent):
        session.add(
            Account(
                tenant_id=tenant.id,
                user_id=user.id,
                account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
                currency="ZAR",
            )
        )
    await session.commit()
    return agent, parent


async def _outcome(session: AsyncSession, tenant: Tenant, agent: User, amount: str):
    """Run the calculation for one amount."""
    return await calculate_commission(
        session,
        tenant_id=tenant.id,
        agent_user_id=agent.id,
        transaction_type="cash_in",
        currency="ZAR",
        amount=Decimal(amount),
    )


@pytest.mark.asyncio
async def test_parent_rate_is_a_percentage_of_the_transaction_amount(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """1% child, 0.5% parent, on R1000 → R10 and R5.

    If the parent rate were a share of the CHILD'S COMMISSION it would be
    0.005 * 10 = R0.05. This assertion is what pins D8.
    """
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant)
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await _outcome(db_session, test_tenant, agent, "1000")

    assert outcome.self_amount == Decimal("10.000000")
    assert outcome.parent_amount == Decimal("5.000000")
    assert outcome.destination == "commission_wallet"
    assert outcome.parent_skip_reason is None
    assert outcome.parent_account_id is not None


@pytest.mark.asyncio
async def test_parent_cap_applies(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """The parent's cap bounds its variable part independently of the child's."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant, parent_commission_cap=Decimal("2"))
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await _outcome(db_session, test_tenant, agent, "1000")
    assert outcome.parent_amount == Decimal("2.000000")
    assert outcome.self_amount == Decimal("10.000000")


@pytest.mark.asyncio
async def test_zero_parent_rate_skips_with_a_reason(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A zero parent rate is a configured decision, recorded as such."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant, parent_variable_commission_pct=Decimal("0"))
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await _outcome(db_session, test_tenant, agent, "1000")
    assert outcome.parent_amount == Decimal("0")
    assert outcome.parent_skip_reason == "parent_zero_rate"


@pytest.mark.asyncio
async def test_no_config_pays_nothing(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Commission stays additive and optional — a missing config is NOT a 422."""
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await _outcome(db_session, test_tenant, agent, "1000")
    assert outcome.self_amount == Decimal("0")
    assert outcome.parent_amount == Decimal("0")
    assert outcome.destination == "main_wallet"


@pytest.mark.asyncio
async def test_fixed_plus_variable_for_both_legs(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Both legs use the same fixed + min(pct*amount, cap) formula."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(
        db_session,
        test_tenant,
        fixed_commission=Decimal("2"),
        parent_fixed_commission=Decimal("1"),
    )
    agent, _ = await _agent_with_parent(db_session, test_tenant)

    outcome = await _outcome(db_session, test_tenant, agent, "1000")
    assert outcome.self_amount == Decimal("12.000000")
    assert outcome.parent_amount == Decimal("6.000000")


@pytest.mark.asyncio
async def test_agent_without_a_parent_still_earns(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Fail-open on the parent leg only (D10) — the child is paid regardless."""
    test_tenant.commission_wallet_enabled = True
    await db_session.commit()
    await _config(db_session, test_tenant)

    agent = User(tenant_id=test_tenant.id, user_type="agent")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    db_session.add(
        Account(
            tenant_id=test_tenant.id,
            user_id=agent.id,
            account_type=ACCOUNT_TYPE_COMMISSION_WALLET,
            currency="ZAR",
        )
    )
    await db_session.commit()

    outcome = await _outcome(db_session, test_tenant, agent, "1000")
    assert outcome.self_amount == Decimal("10.000000")
    assert outcome.parent_amount == Decimal("0")
    assert outcome.parent_skip_reason == "no_parent"
