"""Tests for rewards.service.issue_points_reward.

Validates the ledger structure of a reward (DEBIT system, CREDIT user),
idempotency on replay, and the structural double-issuance guard.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_points_reward
from app.shared.exceptions import UserPointsAccountMissing
from app.shared.models import (
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
        name="first top-up",
        rule_type="first_time",
        transaction_type="top_up",
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
    """DEBIT system_points_issuance, CREDIT user.points_account."""
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
    """Same (user, rule, triggering_event_id) replayed → no second reward."""
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
async def test_issue_reward_fails_when_points_account_missing(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    system_points_account: Account,
) -> None:
    """User without a points_account → UserPointsAccountMissing."""
    rule = _make_first_time_rule(test_tenant)
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    with pytest.raises(UserPointsAccountMissing):
        await issue_points_reward(
            db_session,
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            rule=rule,
            triggering_event_id="evt-no-account",
            reward_value=Decimal("100"),
        )
