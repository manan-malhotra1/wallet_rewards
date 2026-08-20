"""Referral reward payouts.

Drives `evaluate_referral_on_signup` (and `issue_cashback_reward`) directly with
both sides provisioned, which is the realistic shape once a referred user's
accounts exist. Verifies the ledger structure and the fail-open cap behaviour.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rewards.service import issue_cashback_reward
from app.modules.rules.referral_evaluator import evaluate_referral_on_signup
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_CASHBACK_PROVIDER,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    Account,
    Referral,
    RewardEvent,
    Rule,
    Tenant,
    User,
    WalletLimitConfig,
)


async def _make_user(session: AsyncSession, tenant: Tenant) -> User:
    """Create a bare user row directly (no code needed for these tests)."""
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _add_account(
    session: AsyncSession, tenant: Tenant, *, account_type: str, currency: str, user: User | None
) -> Account:
    """Persist and return one account."""
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id if user else None,
        account_type=account_type,
        currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _pending_referral(
    session: AsyncSession, tenant: Tenant, referrer: User, referee: User
) -> Referral:
    """Persist a pending referral linking referee -> referrer."""
    referral = Referral(
        tenant_id=tenant.id,
        referrer_user_id=referrer.id,
        referred_user_id=referee.id,
        code="ABCD2345",
        status="pending",
    )
    session.add(referral)
    await session.commit()
    await session.refresh(referral)
    return referral


@pytest.mark.asyncio
async def test_signup_rewards_both_sides_with_points(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a referral rewards both the referrer and the new customer with points"""
    referrer = await _make_user(db_session, test_tenant)
    referee = await _make_user(db_session, test_tenant)
    await _add_account(
        db_session,
        test_tenant,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
        user=None,
    )
    referrer_pts = await _add_account(
        db_session, test_tenant, account_type=ACCOUNT_TYPE_POINTS, currency="PTS", user=referrer
    )
    referee_pts = await _add_account(
        db_session, test_tenant, account_type=ACCOUNT_TYPE_POINTS, currency="PTS", user=referee
    )
    db_session.add(
        Rule(
            tenant_id=test_tenant.id,
            name="both points",
            rule_type="referral",
            referral_trigger="signup",
            reward_type="points",
            reward_value=Decimal("50"),
            referee_reward_value=Decimal("100"),
            status="active",
        )
    )
    await db_session.commit()
    referral = await _pending_referral(db_session, test_tenant, referrer, referee)

    await evaluate_referral_on_signup(db_session, tenant_id=test_tenant.id, referral=referral)

    ref_bal, _ = await derive_balance(db_session, referrer_pts.id)
    ree_bal, _ = await derive_balance(db_session, referee_pts.id)
    assert ref_bal == Decimal("50")
    assert ree_bal == Decimal("100")

    await db_session.refresh(referral)
    assert referral.status == "rewarded"
    assert referral.referrer_rewarded_at is not None
    assert referral.referee_rewarded_at is not None


@pytest.mark.asyncio
async def test_signup_cashback_credits_wallets_from_system_inflow(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a cashback referral pays both the referrer and the new customer into their wallets"""
    referrer = await _make_user(db_session, test_tenant)
    referee = await _make_user(db_session, test_tenant)
    referrer_w = await _add_account(
        db_session,
        test_tenant,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user=referrer,
    )
    referee_w = await _add_account(
        db_session,
        test_tenant,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user=referee,
    )
    db_session.add(
        Rule(
            tenant_id=test_tenant.id,
            name="both cashback",
            rule_type="referral",
            referral_trigger="signup",
            reward_type="cashback",
            reward_value=Decimal("50"),
            referee_reward_value=Decimal("100"),
            status="active",
        )
    )
    await db_session.commit()
    referral = await _pending_referral(db_session, test_tenant, referrer, referee)

    # Cashback draws from the pre-funded cashback_provider_wallet
    # (Pay-PRD-1270), which is floored at the choke point. `test_tenant`
    # pre-funds it; capture the balance so we can assert the cashback drew
    # EXACTLY 150 regardless of the seed.
    cashback_wallet = (
        await db_session.execute(
            select(Account).where(
                Account.tenant_id == test_tenant.id,
                Account.account_type == ACCOUNT_TYPE_CASHBACK_PROVIDER,
                Account.currency == "ZAR",
            )
        )
    ).scalar_one()
    float_before, _ = await derive_balance(db_session, cashback_wallet.id)

    await evaluate_referral_on_signup(db_session, tenant_id=test_tenant.id, referral=referral)

    ref_bal, _ = await derive_balance(db_session, referrer_w.id)
    ree_bal, _ = await derive_balance(db_session, referee_w.id)
    assert ref_bal == Decimal("50")
    assert ree_bal == Decimal("100")

    # The cashback wallet (funding master) was debited the full 150 (50 + 100).
    inflow_bal, _ = await derive_balance(db_session, cashback_wallet.id)
    assert inflow_bal == float_before - Decimal("150")


@pytest.mark.asyncio
async def test_signup_evaluation_is_idempotent(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a referral never pays either side twice"""
    referrer = await _make_user(db_session, test_tenant)
    referee = await _make_user(db_session, test_tenant)
    await _add_account(
        db_session,
        test_tenant,
        account_type=ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
        user=None,
    )
    referrer_pts = await _add_account(
        db_session, test_tenant, account_type=ACCOUNT_TYPE_POINTS, currency="PTS", user=referrer
    )
    await _add_account(
        db_session, test_tenant, account_type=ACCOUNT_TYPE_POINTS, currency="PTS", user=referee
    )
    db_session.add(
        Rule(
            tenant_id=test_tenant.id,
            name="both points",
            rule_type="referral",
            referral_trigger="signup",
            reward_type="points",
            reward_value=Decimal("50"),
            referee_reward_value=Decimal("100"),
            status="active",
        )
    )
    await db_session.commit()
    referral = await _pending_referral(db_session, test_tenant, referrer, referee)

    await evaluate_referral_on_signup(db_session, tenant_id=test_tenant.id, referral=referral)
    await evaluate_referral_on_signup(db_session, tenant_id=test_tenant.id, referral=referral)

    events = (await db_session.execute(select(RewardEvent))).scalars().all()
    assert len(events) == 2  # one per side, not four
    ref_bal, _ = await derive_balance(db_session, referrer_pts.id)
    assert ref_bal == Decimal("50")


@pytest.mark.asyncio
async def test_cashback_reward_is_cap_exempt(db_session: AsyncSession, test_tenant: Tenant) -> None:
    """Verify a cashback referral reward lands even when it exceeds the wallet limit"""
    referee = await _make_user(db_session, test_tenant)
    wallet = await _add_account(
        db_session,
        test_tenant,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency="ZAR",
        user=referee,
    )
    # Tight cap for the default (consumer) user type.
    db_session.add(
        WalletLimitConfig(
            tenant_id=test_tenant.id,
            currency="ZAR",
            user_type=None,
            max_balance=Decimal("10"),
        )
    )
    rule = Rule(
        tenant_id=test_tenant.id,
        name="cap exempt",
        rule_type="referral",
        referral_trigger="signup",
        reward_type="cashback",
        reward_value=Decimal("100"),
        status="active",
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    await issue_cashback_reward(
        db_session,
        tenant_id=test_tenant.id,
        user_id=referee.id,
        currency="ZAR",
        amount=Decimal("100"),
        rule_id=rule.id,
        triggering_event_id=f"evt-{uuid4().hex}",
    )

    balance, _ = await derive_balance(db_session, wallet.id)
    assert balance == Decimal("100")  # exceeded the 10 cap — reward is fail-open
