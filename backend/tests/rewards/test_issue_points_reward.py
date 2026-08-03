"""Earning points rewards — crediting customers when they qualify.

Validates the ledger structure of a reward (DEBIT system, CREDIT user),
idempotency on replay, and the structural double-issuance guard.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import POINTS_CURRENCY, issue_points_reward
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    Account,
    LedgerEntry,
    RewardEvent,
    Rule,
    Tenant,
    User,
)


def _make_first_time_rule(tenant: Tenant) -> Rule:
    """Helper — instantiate (but don't persist) a first_time rule."""
    return Rule(
        tenant_id=tenant.id,
        name="first fund",
        rule_type="first_time",
        transaction_type="fund",
        reward_type="points",
        reward_value=Decimal("100"),
    )


@pytest.mark.asyncio
async def test_issue_reward_creates_correct_ledger_entries(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Verify a customer's points balance increases when they earn a reward"""
    rule = _make_first_time_rule(test_tenant)
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    reward = await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        rule=rule,
        triggering_event_id="evt-1",
        reward_value=Decimal("100"),
    )

    assert reward.reward_type == "points"
    assert reward.reward_value == Decimal("100")
    assert reward.ledger_entry_id is not None

    # User balance should be +100.
    user_balance, _ = await derive_balance(db_session, user_points.id)
    assert user_balance == Decimal("100")

    # System issuance should be -100.
    system_balance, _ = await derive_balance(db_session, system_points_account.id)
    assert system_balance == Decimal("-100")


@pytest.mark.asyncio
async def test_issue_reward_is_idempotent_on_replay(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_points: Account,
    system_points_account: Account,
) -> None:
    """Verify a repeated reward event does not award points twice"""
    rule = _make_first_time_rule(test_tenant)
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    r1 = await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        rule=rule,
        triggering_event_id="evt-replay",
        reward_value=Decimal("50"),
    )
    r2 = await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        rule=rule,
        triggering_event_id="evt-replay",
        reward_value=Decimal("50"),
    )

    assert r1.id == r2.id

    # Only ONE reward_event row.
    rows = (
        (await db_session.execute(select(RewardEvent).where(RewardEvent.rule_id == rule.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # The CREDIT entry referenced from the reward row exists (no duplicate
    # transactions were written on replay — the ledger's idempotency_key
    # handled it).
    credit = (
        await db_session.execute(select(LedgerEntry).where(LedgerEntry.id == r1.ledger_entry_id))
    ).scalar_one()
    assert credit.entry_type == "CREDIT"
    assert credit.amount == Decimal("50")


@pytest.mark.asyncio
async def test_issue_reward_auto_provisions_points_account_when_missing(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    system_points_account: Account,
) -> None:
    """Verify a first-time earner with no points account still receives their reward"""
    # This user has NO points_account (the `user_points` fixture is deliberately
    # not requested). The reward must still land: issuance auto-provisions the
    # PTS account rather than failing and poisoning the reward pipeline.
    rule = _make_first_time_rule(test_tenant)
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    reward = await issue_points_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        rule=rule,
        triggering_event_id="evt-no-account",
        reward_value=Decimal("100"),
    )

    # A points_account was created for the user, in the platform PTS currency.
    account = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.user_id == test_user.id,
                Account.account_type == ACCOUNT_TYPE_POINTS,
            )
        )
    ).scalar_one()
    assert account.currency == POINTS_CURRENCY

    # And the reward actually credited that freshly-provisioned account.
    assert reward.reward_value == Decimal("100")
    balance, _ = await derive_balance(db_session, account.id)
    assert balance == Decimal("100")
