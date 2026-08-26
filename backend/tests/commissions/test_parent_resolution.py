"""Parent resolution: exactly one level, fail-open with a reason (D9, D10).

A standalone agent with no super-agent is the NORMAL case, not an error. It
must never block their cash-in — so every unpayable-parent path returns a
reason rather than raising.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commissions.resolution import resolve_parent_target
from app.shared.models import (
    ACCOUNT_TYPE_COMMISSION_WALLET,
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    Account,
    Tenant,
    User,
)


async def _user(
    session: AsyncSession, tenant: Tenant, user_type: str, parent: User | None = None
) -> User:
    """A bare user of a given type, optionally hung under a parent."""
    user = User(
        tenant_id=tenant.id,
        user_type=user_type,
        parent_user_id=parent.id if parent is not None else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _wallet(
    session: AsyncSession, tenant: Tenant, user: User, account_type: str
) -> Account:
    """One ZAR account of a type for a user."""
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=account_type,
        currency="ZAR",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_no_parent_returns_a_reason(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """A standalone agent is normal, not an error."""
    agent = await _user(db_session, test_tenant, "agent")

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "no_parent"


@pytest.mark.asyncio
async def test_eligible_parent_resolves_to_their_commission_wallet(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """The happy path: a super-agent parent with a commission wallet."""
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    wallet = await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_COMMISSION_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id == wallet.id
    assert target.skip_reason is None


@pytest.mark.asyncio
async def test_parent_leg_follows_the_child_destination(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Main-wallet rules pay the parent into their MAIN wallet (D6)."""
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    main = await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_FINANCIAL_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="main_wallet",
        currency="ZAR",
    )
    assert target.account_id == main.id


@pytest.mark.asyncio
async def test_consumer_parent_is_skipped(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """An ineligible-category parent is skipped with its own reason."""
    parent = await _user(db_session, test_tenant, "consumer")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    await _wallet(db_session, test_tenant, parent, ACCOUNT_TYPE_FINANCIAL_WALLET)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "parent_ineligible_category"


@pytest.mark.asyncio
async def test_parent_without_the_wallet_is_skipped(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """An eligible parent with no provisioned wallet still doesn't block the child."""
    parent = await _user(db_session, test_tenant, "super_agent")
    agent = await _user(db_session, test_tenant, "agent", parent=parent)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "parent_wallet_missing"


@pytest.mark.asyncio
async def test_grandparent_is_never_walked(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Exactly one level (D9) — the two-level cap from user-types D7."""
    grandparent = await _user(db_session, test_tenant, "super_agent")
    parent = await _user(db_session, test_tenant, "super_agent", parent=grandparent)
    agent = await _user(db_session, test_tenant, "agent", parent=parent)
    gp_wallet = await _wallet(
        db_session, test_tenant, grandparent, ACCOUNT_TYPE_COMMISSION_WALLET
    )
    parent_wallet = await _wallet(
        db_session, test_tenant, parent, ACCOUNT_TYPE_COMMISSION_WALLET
    )

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id == parent_wallet.id
    assert target.account_id != gp_wallet.id


@pytest.mark.asyncio
async def test_cross_tenant_parent_never_resolves(
    db_session: AsyncSession, test_tenant: Tenant, other_tenant: Tenant
) -> None:
    """Tenant isolation (NFR-0220): a parent id from another tenant is invisible."""
    foreign_parent = await _user(db_session, other_tenant, "super_agent")
    await _wallet(db_session, other_tenant, foreign_parent, ACCOUNT_TYPE_COMMISSION_WALLET)

    agent = User(
        tenant_id=test_tenant.id,
        user_type="agent",
        parent_user_id=foreign_parent.id,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    target = await resolve_parent_target(
        db_session,
        tenant_id=test_tenant.id,
        earner_user_id=agent.id,
        destination="commission_wallet",
        currency="ZAR",
    )
    assert target.account_id is None
    assert target.skip_reason == "no_parent"
