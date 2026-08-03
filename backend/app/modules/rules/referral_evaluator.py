"""Referral rule evaluation — Epic 10 / WAL-77 (Pay-PRD-0622).

Referral rules are NOT driven by the generic transaction-event dispatcher in
`evaluator.py`; they have two explicit entry points instead:

  - `evaluate_referral_on_signup`      — fires 'signup'-trigger rules the moment
                                          a referred user is created.
  - `evaluate_referral_on_transaction` — fires 'nth_transaction'-trigger rules
                                          when the referred user reaches their
                                          Nth qualifying COMPLETED transaction.

Both reward the referrer (rule.reward_value) and, when configured, the referee
(rule.referee_reward_value), via points or cashback per `rule.reward_type`.
They are idempotent: the referral's `*_rewarded_at` stamps guard each side, and
the `reward_events (user_id, rule_id, triggering_event_id)` unique index is the
structural backstop (NFR-0110).

Pipeline note (known gap flagged by the composite work): internal transactions
do not yet call the evaluator, and external events are not persisted as
`transactions`. `evaluate_referral_on_transaction` therefore counts from the
`transactions` table and is forward-compatible, but wiring it into the live
transaction path is a separate integration task.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rewards.service import (
    POINTS_CURRENCY,
    issue_cashback_reward,
    issue_points_reward,
)
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    REFERRAL_STATUS_REWARDED,
    REFERRAL_TRIGGER_NTH_TRANSACTION,
    REFERRAL_TRIGGER_SIGNUP,
    REWARD_TYPE_CASHBACK,
    RULE_TYPE_REFERRAL,
    TXN_STATUS_COMPLETED,
    Account,
    Referral,
    Rule,
    Tenant,
    Transaction,
)

# Points always accrue in the shared "PTS" unit account (POINTS_CURRENCY, the
# platform convention). Cashback pays in the tenant base currency instead.


async def _ensure_user_account(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    account_type: str,
    currency: str,
) -> None:
    """Provision the reward-target account for a user if it doesn't exist yet.

    A brand-new referee (rewarded on `signup`) has no accounts provisioned, so a
    referee cashback/points reward would otherwise hit `UserFinancialWalletMissing`
    / `UserPointsAccountMissing`. Since a configured referral reward is an
    explicit intent to pay this user, we get-or-create the single account the
    reward lands in (system provisioning — no admin actor / audit). Scoped to the
    referral reward path only; it does NOT change the strict behaviour of other
    reward types, which still require a pre-existing account.
    """
    existing = (
        await session.execute(
            select(Account.id).where(
                Account.tenant_id == tenant_id,
                Account.user_id == user_id,
                Account.account_type == account_type,
                Account.currency == currency.upper(),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    session.add(
        Account(
            tenant_id=tenant_id,
            user_id=user_id,
            account_type=account_type,
            currency=currency.upper(),
        )
    )
    await session.flush()


async def _active_referral_rules(
    session: AsyncSession, *, tenant_id: UUID, trigger: str
) -> list[Rule]:
    """Return active referral rules in the tenant for a given trigger."""
    result = await session.execute(
        select(Rule).where(
            Rule.tenant_id == tenant_id,
            Rule.status == "active",
            Rule.rule_type == RULE_TYPE_REFERRAL,
            Rule.referral_trigger == trigger,
        )
    )
    return list(result.scalars().all())


async def _tenant_base_currency(session: AsyncSession, tenant_id: UUID) -> str:
    """Resolve the tenant's base currency — the currency cashback is paid in."""
    result = await session.execute(select(Tenant.base_currency).where(Tenant.id == tenant_id))
    return str(result.scalar_one())


async def _reward_one_side(
    session: AsyncSession,
    *,
    rule: Rule,
    tenant_id: UUID,
    base_currency: str,
    user_id: UUID,
    amount: Decimal,
    triggering_event_id: str,
) -> None:
    """Issue a single referral reward to one user, points or cashback per rule.

    Points rewards land in the user's points_account; cashback lands in their
    financial_wallet in the tenant base currency. Both issuers are idempotent.
    """
    if rule.reward_type == REWARD_TYPE_CASHBACK:
        # A newly-signed-up referee may not have a wallet yet — provision it so
        # the promo cashback can land (the "join -> 100 ZAR" case).
        await _ensure_user_account(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
            currency=base_currency,
        )
        await issue_cashback_reward(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            currency=base_currency,
            amount=amount,
            rule_id=rule.id,
            triggering_event_id=triggering_event_id,
        )
    else:
        await _ensure_user_account(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            account_type=ACCOUNT_TYPE_POINTS,
            currency=POINTS_CURRENCY,
        )
        await issue_points_reward(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            rule=rule,
            triggering_event_id=triggering_event_id,
            reward_value=amount,
        )


async def _fire_both_sides(
    session: AsyncSession,
    *,
    rule: Rule,
    referral: Referral,
    tenant_id: UUID,
    base_currency: str,
    triggering_event_id: str,
) -> None:
    """Reward the referrer and (when configured) the referee for one rule.

    Each side is guarded by its `*_rewarded_at` stamp so a re-run never
    double-pays; the reward_events unique index backstops even if a stamp is
    lost. Stamps + status are persisted by the caller's commit.
    """
    now = datetime.now(UTC)

    if referral.referrer_rewarded_at is None:
        await _reward_one_side(
            session,
            rule=rule,
            tenant_id=tenant_id,
            base_currency=base_currency,
            user_id=referral.referrer_user_id,
            amount=Decimal(rule.reward_value),
            triggering_event_id=triggering_event_id,
        )
        referral.referrer_rewarded_at = now

    # Referee reward is optional — only when a non-zero referee_reward_value set.
    referee_value = rule.referee_reward_value
    if referral.referee_rewarded_at is None and referee_value is not None and referee_value > 0:
        await _reward_one_side(
            session,
            rule=rule,
            tenant_id=tenant_id,
            base_currency=base_currency,
            user_id=referral.referred_user_id,
            amount=Decimal(referee_value),
            triggering_event_id=triggering_event_id,
        )
        referral.referee_rewarded_at = now

    referral.status = REFERRAL_STATUS_REWARDED


async def evaluate_referral_on_signup(
    session: AsyncSession, *, tenant_id: UUID, referral: Referral
) -> None:
    """Fire every active 'signup'-trigger referral rule for a fresh referral.

    Called right after a referred user is created (a `referrals` row exists).
    Organic signups have no referral and never reach here.

    Idempotent: re-running with the same referral does not double-pay — the
    per-side stamps short-circuit and the reward_events unique index backstops.

    Args:
        session: Async DB session (committed here — reward issuance commits).
        tenant_id: Tenant scope.
        referral: The pending referral linking referred -> referrer.

    Side effects:
        Issues 0..N rewards, stamps `referrer_rewarded_at` / `referee_rewarded_at`,
        sets `status='rewarded'`, and commits.
    """
    rules = await _active_referral_rules(
        session, tenant_id=tenant_id, trigger=REFERRAL_TRIGGER_SIGNUP
    )
    if not rules:
        return

    base_currency = await _tenant_base_currency(session, tenant_id)
    for rule in rules:
        await _fire_both_sides(
            session,
            rule=rule,
            referral=referral,
            tenant_id=tenant_id,
            base_currency=base_currency,
            # Per (rule, referral) — the two sides differ by user_id, so they
            # never collide on the reward_events unique index.
            triggering_event_id=f"referral_signup:{referral.id}:{rule.id}",
        )
    await session.commit()


async def _count_referee_completed_transactions(
    session: AsyncSession, *, tenant_id: UUID, referred_user_id: UUID, transaction_type: str | None
) -> int:
    """Count the referred user's COMPLETED (optionally typed) transactions."""
    stmt = select(func.count(Transaction.id)).where(
        Transaction.tenant_id == tenant_id,
        Transaction.initiated_by == referred_user_id,
        Transaction.status == TXN_STATUS_COMPLETED,
    )
    if transaction_type is not None:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    return int((await session.execute(stmt)).scalar_one())


async def evaluate_referral_on_transaction(
    session: AsyncSession, *, tenant_id: UUID, referred_user_id: UUID
) -> None:
    """Fire 'nth_transaction'-trigger referral rules for the referred user.

    When the referred user's count of qualifying COMPLETED transactions reaches
    a rule's `referral_trigger_n`, reward both sides once. `rule.transaction_type`
    (when set) narrows what counts as qualifying; NULL counts every completed
    transaction.

    Idempotent: the referral's stamps + the reward_events unique index prevent a
    second payout once fired.

    Pipeline note: this path is not yet wired into the live transaction flow (see
    the module docstring) — it is complete and unit-tested, ready to be called
    when the transaction pipeline emits into the evaluator.

    Args:
        session: Async DB session (committed here on a fire).
        tenant_id: Tenant scope.
        referred_user_id: The referred user whose transaction just completed.

    Side effects:
        On reaching the threshold: issues rewards, stamps the referral, sets
        `status='rewarded'`, and commits. A no-op otherwise.
    """
    referral = (
        await session.execute(
            select(Referral).where(
                Referral.tenant_id == tenant_id,
                Referral.referred_user_id == referred_user_id,
            )
        )
    ).scalar_one_or_none()
    if referral is None:
        return  # Not a referred user — nothing to do.

    rules = await _active_referral_rules(
        session, tenant_id=tenant_id, trigger=REFERRAL_TRIGGER_NTH_TRANSACTION
    )
    if not rules:
        return

    base_currency = await _tenant_base_currency(session, tenant_id)
    fired = False
    for rule in rules:
        if rule.referral_trigger_n is None:
            continue  # Malformed; schema validation covers it.
        count = await _count_referee_completed_transactions(
            session,
            tenant_id=tenant_id,
            referred_user_id=referred_user_id,
            transaction_type=rule.transaction_type,
        )
        if count < rule.referral_trigger_n:
            continue  # Threshold not reached yet.

        await _fire_both_sides(
            session,
            rule=rule,
            referral=referral,
            tenant_id=tenant_id,
            base_currency=base_currency,
            triggering_event_id=f"referral_nth:{referral.id}:{rule.id}",
        )
        fired = True

    if fired:
        await session.commit()
