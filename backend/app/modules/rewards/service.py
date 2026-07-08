"""Rewards service — issue points to a user when a rule fires.

Posts a balanced ledger transaction:
    DEBIT  system_points_issuance   (tenant's master source)
    CREDIT user's points_account

Inserts a `reward_events` row linking the rule + triggering event +
ledger entry. The UNIQUE INDEX on (user_id, rule_id, triggering_event_id)
is the idempotency guard (NFR-0110) — duplicates are caught at insert and
treated as no-op.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger import (
    LedgerEntryRequest,
    PostTransactionRequest,
    post_transaction,
)
from app.shared.exceptions import (
    SystemPointsIssuanceMissing,
    UserPointsAccountMissing,
)
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    REWARD_TYPE_POINTS,
    Account,
    LedgerEntry,
    RewardEvent,
    Rule,
)


async def _find_user_points_account(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> Account:
    """Return the user's points_account in this tenant, or raise."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_POINTS,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise UserPointsAccountMissing()
    return account


async def _find_system_points_issuance(session: AsyncSession, tenant_id: UUID) -> Account:
    """Return the tenant's master system_points_issuance account, or raise."""
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_SYSTEM_POINTS_ISSUANCE,
            Account.user_id.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise SystemPointsIssuanceMissing()
    return account


async def _find_existing_reward_event(
    session: AsyncSession,
    user_id: UUID,
    rule_id: UUID,
    triggering_event_id: str,
) -> RewardEvent | None:
    """Check whether this (user, rule, event) triple already has a reward."""
    result = await session.execute(
        select(RewardEvent).where(
            RewardEvent.user_id == user_id,
            RewardEvent.rule_id == rule_id,
            RewardEvent.triggering_event_id == triggering_event_id,
        )
    )
    return result.scalar_one_or_none()


async def issue_points_reward(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    rule: Rule,
    triggering_event_id: str,
    reward_value: Decimal,
) -> RewardEvent:
    """Credit reward points to a user's points_account.

    Idempotent. If a reward_events row already exists for (user, rule,
    triggering_event_id), returns it without writing new ledger entries.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: User to be rewarded.
        rule: The rule that fired.
        triggering_event_id: External event_id (Kafka) or internal txn_id
            that caused this firing. Used for the idempotency guard.
        reward_value: Points to credit (typically rule.reward_value, but
            passed explicitly so callers can apply multipliers in future).

    Returns:
        The persisted RewardEvent.

    Raises:
        UserPointsAccountMissing: 422 — user has no points_account.
        SystemPointsIssuanceMissing: 500 — tenant misconfigured.
    """
    # Fast-path: already issued — return existing row.
    existing = await _find_existing_reward_event(session, user_id, rule.id, triggering_event_id)
    if existing is not None:
        return existing

    user_points = await _find_user_points_account(session, tenant_id, user_id)
    system_issuance = await _find_system_points_issuance(session, tenant_id)

    # Epic 10 / WAL-78: apply any matching bonus multiplier BEFORE the
    # budget check + ledger write. The multiplied amount is what the
    # budget guards against and what ends up on the ledger. Lazy import
    # to avoid a service-layer cycle.
    from app.modules.multipliers.service import (
        resolve_multiplier_for_issuance,
    )

    multiplier = await resolve_multiplier_for_issuance(
        session, tenant_id=tenant_id, rule_id=rule.id, user_id=user_id
    )
    effective_value = (reward_value * multiplier).quantize(Decimal("0.000001"))

    # Phase G.1: every reward issuance is budget-checked BEFORE writing
    # the ledger. `check_budget_available` locks each matching budget row
    # FOR UPDATE, so two concurrent fires can't both pass at 99%
    # consumption. Raises BudgetExceeded on breach.
    from app.modules.budgets.service import check_budget_available

    await check_budget_available(
        session,
        tenant_id=tenant_id,
        rule_id=rule.id,
        currency=user_points.currency,
        amount=effective_value,
    )

    # Use the multiplied amount for ledger + reward_events from this point on.
    reward_value = effective_value

    # The idempotency_key on the underlying transaction is deterministic —
    # replays will hit the post_transaction idempotency guard, not write
    # a second transaction.
    idempotency_key = f"reward:{rule.id}:{user_id}:{triggering_event_id}"

    txn = await post_transaction(
        session,
        PostTransactionRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            transaction_type="reward_issuance",
            currency=user_points.currency,
            entries=[
                LedgerEntryRequest(
                    account_id=system_issuance.id,
                    entry_type=ENTRY_DEBIT,
                    amount=reward_value,
                ),
                LedgerEntryRequest(
                    account_id=user_points.id,
                    entry_type=ENTRY_CREDIT,
                    amount=reward_value,
                ),
            ],
            initiated_by=None,  # system-initiated
            amount=reward_value,
        ),
    )

    # Find the CREDIT entry on the user's points account so we can link it
    # from reward_events for audit traceability.
    credit_entry = (
        await session.execute(
            select(LedgerEntry).where(
                LedgerEntry.transaction_id == txn.id,
                LedgerEntry.account_id == user_points.id,
                LedgerEntry.entry_type == ENTRY_CREDIT,
            )
        )
    ).scalar_one_or_none()

    # Insert the reward_events row. The unique index catches concurrent
    # races — if another coroutine got here first, refetch and return.
    reward = RewardEvent(
        user_id=user_id,
        rule_id=rule.id,
        triggering_event_id=triggering_event_id,
        reward_type=REWARD_TYPE_POINTS,
        reward_value=reward_value,
        # Persist the multiplier so reports can distinguish base vs boosted.
        multiplier_applied=multiplier,
        ledger_entry_id=credit_entry.id if credit_entry else None,
    )
    session.add(reward)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _find_existing_reward_event(session, user_id, rule.id, triggering_event_id)
        if existing is None:
            raise  # unexpected — bubble up
        return existing

    await session.refresh(reward)
    return reward
