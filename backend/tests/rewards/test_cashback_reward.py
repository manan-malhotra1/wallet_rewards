"""Cashback reward regression tests.

Guards two money-path fixes:
  1. A cashback-typed rule must pay CASHBACK (credit the financial wallet),
     never points — both directly (`issue_cashback_reward`) and via the shared
     `evaluate_and_issue_firings` dispatch used by the outbox + Kafka paths.
  2. Cashback issuance is budget-checked BEFORE the ledger write, so a
     rule-scoped (campaign-local) budget caps the operator float drain.

`test_tenant` pre-funds the ZAR cashback_provider_wallet (Pay-PRD-1270), so
cashback debits don't trip its floor. `user_wallet` is the test user's ZAR financial wallet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.events.schemas import NormalisedEvent
from app.modules.events.service import evaluate_and_issue_firings
from app.modules.rewards.service import issue_cashback_reward
from app.shared.exceptions import BudgetExceeded
from app.shared.models import Account, RewardBudget, Rule, Tenant, User


async def _make_cashback_rule(
    session: AsyncSession,
    tenant: Tenant,
    *,
    rule_type: str = "first_time",
    txn_type: str = "p2p",
    currency: str = "ZAR",
    value: str = "10",
    count_threshold: int | None = None,
) -> Rule:
    """Persist an active cashback rule (reward_currency set)."""
    rule = Rule(
        tenant_id=tenant.id,
        name="cashback rule",
        rule_type=rule_type,
        transaction_type=txn_type,
        count_threshold=count_threshold,
        reward_type="cashback",
        reward_value=Decimal(value),
        reward_currency=currency,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


def _budget(tenant: Tenant, rule: Rule, cap: str) -> RewardBudget:
    """A rule-scoped (campaign-local) ZAR budget with the given cap."""
    return RewardBudget(
        tenant_id=tenant.id,
        scope_type="rule",
        scope_id=rule.id,
        currency="ZAR",
        window_type="rolling_24h",
        cap_amount=Decimal(cap),
        status="active",
    )


def _event(tenant: Tenant, user: User, *, event_id: str) -> NormalisedEvent:
    """A normalised ZAR p2p event for the test user."""
    return NormalisedEvent(
        event_id=event_id,
        source_key="internal:wallet",
        tenant_id=tenant.id,
        user_id=user.id,
        transaction_type="p2p",
        amount=Decimal("50"),
        currency="ZAR",
        merchant_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_cashback_credits_financial_wallet_not_points(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
) -> None:
    """Verify a cashback reward credits the user's financial wallet in cash"""
    rule = await _make_cashback_rule(db_session, test_tenant, value="10")

    reward = await issue_cashback_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        currency="ZAR",
        amount=Decimal("10"),
        rule_id=rule.id,
        triggering_event_id="evt-cb-1",
    )

    assert reward.reward_type == "cashback"
    assert reward.reward_value == Decimal("10")
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("10")


@pytest.mark.asyncio
async def test_cashback_blocked_by_rule_scoped_budget(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,  # must exist — issuance resolves the wallet before the budget check
) -> None:
    """Verify a campaign-local budget below the reward blocks the cashback payout"""
    rule = await _make_cashback_rule(db_session, test_tenant, value="10")
    db_session.add(_budget(test_tenant, rule, cap="5"))  # cap < reward
    await db_session.commit()

    # The budget check runs BEFORE any ledger write, so raising here proves no
    # cashback was posted — the cashback wallet is never touched.
    with pytest.raises(BudgetExceeded):
        await issue_cashback_reward(
            db_session,
            tenant_id=test_tenant.id,
            user_id=test_user.id,
            currency="ZAR",
            amount=Decimal("10"),
            rule_id=rule.id,
            triggering_event_id="evt-cb-2",
        )


@pytest.mark.asyncio
async def test_cashback_within_budget_is_issued(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
) -> None:
    """Verify cashback still pays out when it fits within the budget cap"""
    rule = await _make_cashback_rule(db_session, test_tenant, value="10")
    db_session.add(_budget(test_tenant, rule, cap="10"))  # cap == reward
    await db_session.commit()

    reward = await issue_cashback_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=test_user.id,
        currency="ZAR",
        amount=Decimal("10"),
        rule_id=rule.id,
        triggering_event_id="evt-cb-3",
    )

    assert reward.reward_type == "cashback"
    balance, _ = await derive_balance(db_session, user_wallet.id)
    assert balance == Decimal("10")


@pytest.mark.asyncio
async def test_evaluate_and_issue_routes_cashback_to_wallet(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    user_wallet: Account,
    user_points: Account,
) -> None:
    """Verify the shared firing dispatch pays a cashback rule as cash, not points"""
    # A first_time cashback rule fires once on the matching p2p event.
    await _make_cashback_rule(
        db_session, test_tenant, rule_type="first_time", txn_type="p2p", value="10"
    )

    event = _event(test_tenant, test_user, event_id="evt-d1")
    firings = await evaluate_and_issue_firings(db_session, event)

    assert len(firings) == 1
    assert firings[0].reward_type == "cashback"

    # The financial wallet got the cash; the points account was left untouched.
    wallet_balance, _ = await derive_balance(db_session, user_wallet.id)
    assert wallet_balance == Decimal("10")
    points_balance, _ = await derive_balance(db_session, user_points.id)
    assert points_balance == Decimal("0")
