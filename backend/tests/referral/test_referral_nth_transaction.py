"""Referral rewards after enough transactions.

The referral fires only once the referred user reaches N qualifying COMPLETED
transactions — not before — and never twice. Transactions are inserted directly
(the live transaction pipeline is not yet wired to the evaluator; see
referral_evaluator module docstring).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.rules.referral_evaluator import evaluate_referral_on_transaction
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    TXN_STATUS_COMPLETED,
    Account,
    Referral,
    RewardEvent,
    Rule,
    Tenant,
    Transaction,
    User,
)


async def _make_user(session: AsyncSession, tenant: Tenant) -> User:
    user = User(tenant_id=tenant.id)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _add_points_account(session: AsyncSession, tenant: Tenant, user: User | None) -> Account:
    acct = Account(
        tenant_id=tenant.id,
        user_id=user.id if user else None,
        account_type=ACCOUNT_TYPE_POINTS if user else ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
        currency="PTS",
    )
    session.add(acct)
    await session.commit()
    await session.refresh(acct)
    return acct


async def _add_completed_txn(session: AsyncSession, tenant: Tenant, user: User) -> None:
    """Insert one COMPLETED p2p transaction attributed to the user."""
    session.add(
        Transaction(
            tenant_id=tenant.id,
            idempotency_key=f"txn-{uuid4().hex}",
            transaction_type="p2p",
            status=TXN_STATUS_COMPLETED,
            initiated_by=user.id,
            amount=Decimal("10"),
            currency="ZAR",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_nth_transaction_fires_only_at_threshold_and_once(
    db_session: AsyncSession, test_tenant: Tenant
) -> None:
    """Verify a referral rewards the referrer only after enough new-customer transactions"""
    referrer = await _make_user(db_session, test_tenant)
    referee = await _make_user(db_session, test_tenant)
    await _add_points_account(db_session, test_tenant, None)
    referrer_pts = await _add_points_account(db_session, test_tenant, referrer)
    await _add_points_account(db_session, test_tenant, referee)

    rule = Rule(
        tenant_id=test_tenant.id,
        name="third transaction",
        rule_type="referral",
        referral_trigger="nth_transaction",
        referral_trigger_n=3,
        transaction_type="p2p",
        reward_type="points",
        reward_value=Decimal("50"),
        referee_reward_value=Decimal("100"),
        status="active",
    )
    db_session.add(rule)
    db_session.add(
        Referral(
            tenant_id=test_tenant.id,
            referrer_user_id=referrer.id,
            referred_user_id=referee.id,
            code="NTHCODE2",
            status="pending",
        )
    )
    await db_session.commit()

    # Two completed txns — below threshold.
    await _add_completed_txn(db_session, test_tenant, referee)
    await _add_completed_txn(db_session, test_tenant, referee)
    await evaluate_referral_on_transaction(
        db_session, tenant_id=test_tenant.id, referred_user_id=referee.id
    )
    events = (await db_session.execute(select(RewardEvent))).scalars().all()
    assert events == []
    bal, _ = await derive_balance(db_session, referrer_pts.id)
    assert bal == Decimal("0")

    # Third completed txn — reaches threshold.
    await _add_completed_txn(db_session, test_tenant, referee)
    await evaluate_referral_on_transaction(
        db_session, tenant_id=test_tenant.id, referred_user_id=referee.id
    )
    bal, _ = await derive_balance(db_session, referrer_pts.id)
    assert bal == Decimal("50")
    referral = (
        await db_session.execute(select(Referral).where(Referral.referred_user_id == referee.id))
    ).scalar_one()
    assert referral.status == "rewarded"

    # Re-running does not double-pay.
    await evaluate_referral_on_transaction(
        db_session, tenant_id=test_tenant.id, referred_user_id=referee.id
    )
    events = (await db_session.execute(select(RewardEvent))).scalars().all()
    assert len(events) == 2  # referrer + referee, once each
    bal, _ = await derive_balance(db_session, referrer_pts.id)
    assert bal == Decimal("50")
