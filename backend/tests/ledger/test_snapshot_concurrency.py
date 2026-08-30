"""Cached balances survive concurrent first writes to a brand-new account.

A points account is provisioned lazily, on the reward that first credits it
(`rewards.service._get_or_create_user_points_account`), so its snapshot row does
not exist yet either. Several rewards for the same user can land at once, and
every one of them takes the create-the-snapshot branch of
`ledger.snapshots.apply_deltas` simultaneously.

A live 50-way load run left 3 of 413 accounts with a cached balance that
disagreed with the ledger — always on the points path, always short by exactly
one posting on both legs. These tests reproduce that shape directly.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.modules.ledger.snapshots import sum_from_ledger
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    Account,
    AccountBalanceSnapshot,
    Tenant,
    User,
)

_AWARD = Decimal("50")


async def _fresh_accounts(
    session: AsyncSession, tenant: Tenant, user: User
) -> tuple[Account, Account]:
    """A points account with NO snapshot row, plus its system issuance counterpart."""
    points = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_POINTS,
        currency="PTS",
    )
    issuance = Account(
        tenant_id=tenant.id,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    session.add_all([points, issuance])
    await session.commit()
    await session.refresh(points)
    await session.refresh(issuance)
    return points, issuance


async def _award(
    factory: async_sessionmaker[AsyncSession],
    tenant: Tenant,
    points_id,
    issuance_id,
) -> None:
    """Post one reward-shaped transaction on its own session/connection."""
    async with factory() as session:
        await post_transaction(
            session,
            PostTransactionRequest(
                tenant_id=tenant.id,
                idempotency_key=f"reward-{uuid4().hex}",
                transaction_type="reward_issuance",
                currency="PTS",
                entries=[
                    LedgerEntryRequest(
                        account_id=issuance_id, entry_type=ENTRY_DEBIT, amount=_AWARD
                    ),
                    LedgerEntryRequest(
                        account_id=points_id, entry_type=ENTRY_CREDIT, amount=_AWARD
                    ),
                ],
            ),
        )


async def _assert_no_drift(session: AsyncSession, *account_ids) -> None:
    """Every named account's cached balance must equal its ledger balance."""
    drifted = []
    for account_id in account_ids:
        ledger_balance, _ = await sum_from_ledger(session, account_id)
        cached = (
            await session.execute(
                select(AccountBalanceSnapshot.balance).where(
                    AccountBalanceSnapshot.account_id == account_id
                )
            )
        ).scalar_one_or_none()
        if cached is None or Decimal(cached) != ledger_balance:
            drifted.append(f"  {account_id}: cached={cached} ledger={ledger_balance}")
    assert not drifted, "cached balance drifted from the ledger:\n" + "\n".join(drifted)


@pytest.mark.asyncio
async def test_concurrent_first_awards_do_not_lose_a_delta(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify simultaneous first credits to a new account all land

    Every one of these races the branch that CREATES the snapshot row, which is
    the one shape that can discard a concurrent increment.
    """
    points, issuance = await _fresh_accounts(db_session, test_tenant, test_user)

    awards = 8
    await asyncio.gather(
        *(_award(session_factory, test_tenant, points.id, issuance.id) for _ in range(awards))
    )

    ledger_balance, _ = await sum_from_ledger(db_session, points.id)
    assert ledger_balance == _AWARD * awards, "ledger itself should hold every award"
    await _assert_no_drift(db_session, points.id, issuance.id)


@pytest.mark.asyncio
async def test_concurrent_awards_on_an_established_account_do_not_drift(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the steady-state path is race-free once the snapshot row exists"""
    points, issuance = await _fresh_accounts(db_session, test_tenant, test_user)

    # First award serially, so the snapshot row exists before the race.
    await _award(session_factory, test_tenant, points.id, issuance.id)

    await asyncio.gather(
        *(_award(session_factory, test_tenant, points.id, issuance.id) for _ in range(8))
    )

    await _assert_no_drift(db_session, points.id, issuance.id)


@pytest.mark.asyncio
async def test_concurrent_rewards_through_the_real_issuance_path_do_not_drift(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify the live reward path is drift-free when the points account is new

    Exercises `issue_points_reward` rather than posting directly, so the lazy
    account provisioning runs — both `_get_or_create_user_points_account` and
    `get_or_create_system_points_issuance` call `session.rollback()` when they
    lose an INSERT race, which discards whatever else that session had staged.
    """
    from app.modules.rewards.service import issue_points_reward
    from app.shared.models import Rule

    rule = Rule(
        tenant_id=test_tenant.id,
        name="concurrent-award",
        rule_type="first_time",
        transaction_type="fund",
        reward_type="points",
        reward_value=_AWARD,
        status="active",
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    async def _issue(n: int) -> None:
        # A DISTINCT triggering_event_id per call, so the reward_events
        # idempotency guard never collapses them into one issuance.
        async with session_factory() as session:
            await issue_points_reward(
                session,
                tenant_id=test_tenant.id,
                user_id=test_user.id,
                rule=rule,
                triggering_event_id=f"evt-{n}",
                reward_value=_AWARD,
            )

    results = await asyncio.gather(*(_issue(n) for n in range(8)), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]

    points = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_POINTS,
            )
        )
    ).scalar_one()
    issuance = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            )
        )
    ).scalar_one()

    await _assert_no_drift(db_session, points.id, issuance.id)
    assert not failures, f"issuance raised: {failures}"
