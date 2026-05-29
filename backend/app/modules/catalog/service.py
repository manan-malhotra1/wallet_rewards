"""Catalog service — read-side aggregations over the ledger.

All numbers are derived from `ledger_entries` (the source of truth) so they
are always consistent with the user's actual balance. Snapshot tables are
intentionally NOT used here — see ledger-invariants.md and the
`account_balance_snapshots` design note.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts.service import derive_balance
from app.modules.catalog.schemas import (
    CatalogSummaryResponse,
    PointsHistoryItem,
    PointsSummary,
    RedemptionHistoryItem,
)
from app.shared.models import (
    ACCOUNT_TYPE_POINTS,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Redemption,
    RewardEvent,
    Rule,
    Transaction,
)


async def _find_user_points_account(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> Account | None:
    """Return the user's points_account, or None if missing.

    Returns None (not raises) because the catalog endpoint may be called for
    a user who hasn't been issued any points yet — the response should still
    succeed with `points: null`.
    """
    result = await session.execute(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.user_id == user_id,
            Account.account_type == ACCOUNT_TYPE_POINTS,
        )
    )
    return result.scalar_one_or_none()


async def _sum_by_transaction_type(
    session: AsyncSession,
    account_id: UUID,
    entry_type: str,
    transaction_type: str,
) -> Decimal:
    """SUM(ledger_entries.amount) filtered by entry_type + parent txn type.

    Used for "lifetime earned" (CREDIT + reward_issuance) and
    "lifetime redeemed" (DEBIT + redemption, status=COMPLETED).
    """
    result = await session.execute(
        select(LedgerEntry.amount, Transaction.transaction_type, Transaction.status)
        .join(Transaction, Transaction.id == LedgerEntry.transaction_id)
        .where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.entry_type == entry_type,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
            Transaction.transaction_type == transaction_type,
        )
    )
    total = Decimal("0")
    for amount, _, _ in result.all():
        total += Decimal(amount)
    return total


async def get_user_summary(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> CatalogSummaryResponse:
    """Build the catalog summary for one user (Pay-PRD-0970).

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: The user whose catalog we want.

    Returns:
        CatalogSummaryResponse — `points` is None if the user has no
        points_account in this tenant.
    """
    points_account = await _find_user_points_account(session, tenant_id, user_id)
    if points_account is None:
        return CatalogSummaryResponse(
            user_id=user_id, tenant_id=tenant_id, points=None
        )

    balance, reserved = await derive_balance(session, points_account.id)
    lifetime_earned = await _sum_by_transaction_type(
        session, points_account.id, ENTRY_CREDIT, "reward_issuance"
    )
    lifetime_redeemed = await _sum_by_transaction_type(
        session, points_account.id, ENTRY_DEBIT, "redemption"
    )

    return CatalogSummaryResponse(
        user_id=user_id,
        tenant_id=tenant_id,
        points=PointsSummary(
            currency=points_account.currency,
            available=balance - reserved,
            reserved=reserved,
            lifetime_earned=lifetime_earned,
            lifetime_redeemed=lifetime_redeemed,
        ),
    )


async def get_user_redemption_history(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[RedemptionHistoryItem]:
    """Return the user's redemption history newest-first (Pay-PRD-1030)."""
    result = await session.execute(
        select(Redemption)
        .where(
            Redemption.tenant_id == tenant_id,
            Redemption.user_id == user_id,
        )
        .order_by(Redemption.created_at.desc())
    )
    return [RedemptionHistoryItem.model_validate(r) for r in result.scalars().all()]


async def get_user_points_history(
    session: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[PointsHistoryItem]:
    """Return every ledger entry on the user's points_account, newest first.

    Joins ledger_entries -> transactions -> (optional) reward_events -> rules
    so each entry shows whether it came from a reward (and which rule fired)
    or a redemption. Tenant-isolated via the points_account lookup — if the
    user has no points_account in this tenant, returns an empty list (NOT
    a 404, matching the summary endpoint's behaviour).

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        user_id: The user whose points history we want.

    Returns:
        List of PointsHistoryItem ordered by entry timestamp DESC.
    """
    account = await _find_user_points_account(session, tenant_id, user_id)
    if account is None:
        return []

    stmt = (
        select(
            LedgerEntry.id,
            LedgerEntry.entry_type,
            LedgerEntry.amount,
            LedgerEntry.status,
            LedgerEntry.created_at,
            Transaction.transaction_type,
            Rule.name,
            RewardEvent.triggering_event_id,
        )
        .join(Transaction, Transaction.id == LedgerEntry.transaction_id)
        .outerjoin(
            RewardEvent, RewardEvent.ledger_entry_id == LedgerEntry.id
        )
        .outerjoin(Rule, Rule.id == RewardEvent.rule_id)
        .where(LedgerEntry.account_id == account.id)
        .order_by(LedgerEntry.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        PointsHistoryItem(
            ledger_entry_id=row.id,
            direction=row.entry_type,
            amount=Decimal(row.amount),
            status=row.status,
            transaction_type=row.transaction_type,
            rule_name=row.name,
            triggering_event_id=row.triggering_event_id,
            occurred_at=row.created_at,
        )
        for row in rows
    ]
