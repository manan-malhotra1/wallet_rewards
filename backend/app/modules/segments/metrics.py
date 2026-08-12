"""Metric registry for dynamic segments — name → set-based value builder.

Every builder computes ONE aggregate per tenant as {user_id: Decimal},
covering all users of the tenant in a single query (no per-user loops).
Adding a metric = add a builder here + the name in criteria.MetricName;
tests/segments/test_metrics.py::test_registry_matches_dsl_vocabulary
enforces the two stay in sync (a module-level assert would be stripped
under `python -O`, so the test is the sole source of truth for this).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.shared.models import (
    ENTRY_CREDIT,
    ENTRY_STATUS_COMPLETED,
    REDEMPTION_STATUS_COMPLETED,
    REFERRAL_STATUS_REWARDED,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Redemption,
    Referral,
    RewardEvent,
    Transaction,
    User,
)
from app.shared.models.accounts import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
)

# Users who never transacted sort as "very long ago" for recency criteria.
NEVER_TRANSACTED_DAYS = Decimal(99999)

Builder = Callable[..., Awaitable[dict[UUID, Decimal]]]


def _window_start(window_days: int | None) -> datetime | None:
    """Lower created_at bound for a rolling window, or None for lifetime.

    Args:
        window_days: Rolling window length in days, or None for no bound.

    Returns:
        The UTC instant `window_days` ago, or None when `window_days` is None.
    """
    if window_days is None:
        return None
    return datetime.now(UTC) - timedelta(days=window_days)


async def _rows_to_map(session: AsyncSession, stmt: Select[Any]) -> dict[UUID, Decimal]:
    """Execute a (user_id, value) select into a {user_id: Decimal} map.

    Args:
        session: Async DB session.
        stmt: A SELECT yielding exactly two columns: user_id, aggregate value.

    Returns:
        Mapping of user_id to Decimal value, skipping any NULL user_id rows
        (e.g. transactions with no `initiated_by`).
    """
    result = await session.execute(stmt)
    return {row[0]: Decimal(row[1]) for row in result.all() if row[0] is not None}


async def _txn_aggregate(
    session: AsyncSession,
    tenant_id: UUID,
    agg: ColumnElement[Any],
    txn_type: str | None,
    window_days: int | None,
) -> dict[UUID, Decimal]:
    """Shared COMPLETED-transactions aggregate grouped by initiator.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope the query to (NFR-0220).
        agg: The SQLAlchemy aggregate expression to select (count, sum, ...).
        txn_type: Optional `transaction_type` filter.
        window_days: Optional rolling window filter on `created_at`.

    Returns:
        Mapping of initiating user_id to the aggregate Decimal value.
    """
    stmt = (
        select(Transaction.initiated_by, agg)
        .where(Transaction.tenant_id == tenant_id, Transaction.status == TXN_STATUS_COMPLETED)
        .group_by(Transaction.initiated_by)
    )
    if txn_type is not None:
        stmt = stmt.where(Transaction.transaction_type == txn_type)
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(Transaction.created_at >= start)
    return await _rows_to_map(session, stmt)


async def txn_count(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
) -> dict[UUID, Decimal]:
    """COMPLETED transaction count per initiating user."""
    return await _txn_aggregate(session, tenant_id, func.count(), txn_type, window_days)


async def txn_sum(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
) -> dict[UUID, Decimal]:
    """COMPLETED transaction amount sum per initiating user."""
    return await _txn_aggregate(
        session,
        tenant_id,
        func.coalesce(func.sum(Transaction.amount), 0),
        txn_type,
        window_days,
    )


async def _balance(
    session: AsyncSession, tenant_id: UUID, account_type: str
) -> dict[UUID, Decimal]:
    """Signed COMPLETED ledger sum per user for one account type.

    Mirrors `ledger.service.sum_completed_balance` (CREDIT +, DEBIT -),
    computed set-based across every user account of the tenant in one query.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope the query to (NFR-0220).
        account_type: One of the `ACCOUNT_TYPE_*` constants to sum over.

    Returns:
        Mapping of user_id to net Decimal balance for that account type.
    """
    signed = func.coalesce(
        func.sum(
            case(
                (LedgerEntry.entry_type == ENTRY_CREDIT, LedgerEntry.amount),
                else_=-LedgerEntry.amount,
            )
        ),
        0,
    )
    stmt = (
        select(Account.user_id, signed)
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            Account.user_id.is_not(None),
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
        .group_by(Account.user_id)
    )
    return await _rows_to_map(session, stmt)


async def wallet_balance(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Financial-wallet balance per user."""
    return await _balance(session, tenant_id, ACCOUNT_TYPE_FINANCIAL_WALLET)


async def points_balance(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Points-account balance per user."""
    return await _balance(session, tenant_id, ACCOUNT_TYPE_POINTS)


async def points_redeemed(
    session: AsyncSession, tenant_id: UUID, *, window_days: int | None = None, **_: object
) -> dict[UUID, Decimal]:
    """COMPLETED redemption points per user."""
    stmt = (
        select(Redemption.user_id, func.coalesce(func.sum(Redemption.points_amount), 0))
        .where(Redemption.tenant_id == tenant_id, Redemption.status == REDEMPTION_STATUS_COMPLETED)
        .group_by(Redemption.user_id)
    )
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(Redemption.created_at >= start)
    return await _rows_to_map(session, stmt)


async def rewards_earned(
    session: AsyncSession, tenant_id: UUID, *, window_days: int | None = None, **_: object
) -> dict[UUID, Decimal]:
    """Reward events per user (tenant-scoped via User join — RewardEvent has no tenant_id)."""
    stmt = (
        select(RewardEvent.user_id, func.count())
        .join(User, User.id == RewardEvent.user_id)
        .where(User.tenant_id == tenant_id)
        .group_by(RewardEvent.user_id)
    )
    start = _window_start(window_days)
    if start is not None:
        stmt = stmt.where(RewardEvent.created_at >= start)
    return await _rows_to_map(session, stmt)


async def account_age_days(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Days since signup per user."""
    age = func.extract("epoch", func.now() - User.created_at) / 86400
    stmt = select(User.id, age).where(User.tenant_id == tenant_id)
    return await _rows_to_map(session, stmt)


async def days_since_last_txn(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Days since the user's last COMPLETED transaction (99999 if never)."""
    last = func.max(Transaction.created_at)
    days = func.extract("epoch", func.now() - last) / 86400
    stmt = (
        select(Transaction.initiated_by, days)
        .where(Transaction.tenant_id == tenant_id, Transaction.status == TXN_STATUS_COMPLETED)
        .group_by(Transaction.initiated_by)
    )
    values = await _rows_to_map(session, stmt)
    users = await session.execute(select(User.id).where(User.tenant_id == tenant_id))
    for (user_id,) in users.all():
        values.setdefault(user_id, NEVER_TRANSACTED_DAYS)
    return values


async def referral_count(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Rewarded referrals per referrer."""
    stmt = (
        select(Referral.referrer_user_id, func.count())
        .where(Referral.tenant_id == tenant_id, Referral.status == REFERRAL_STATUS_REWARDED)
        .group_by(Referral.referrer_user_id)
    )
    return await _rows_to_map(session, stmt)


METRIC_BUILDERS: dict[str, Builder] = {
    "txn_count": txn_count,
    "txn_sum": txn_sum,
    "wallet_balance": wallet_balance,
    "points_balance": points_balance,
    "points_redeemed": points_redeemed,
    "rewards_earned": rewards_earned,
    "account_age_days": account_age_days,
    "days_since_last_txn": days_since_last_txn,
    "referral_count": referral_count,
}


async def compute_metric(
    session: AsyncSession,
    tenant_id: UUID,
    metric: str,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
) -> dict[UUID, Decimal]:
    """Dispatch one metric computation to its registered builder.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope the computation to (NFR-0220).
        metric: A key of `METRIC_BUILDERS` (kept in sync with `criteria.MetricName`).
        txn_type: Forwarded to transactional metrics; ignored by others.
        window_days: Forwarded to windowed metrics; ignored by others.

    Returns:
        Mapping of user_id to the metric's Decimal value for every user that
        has a non-zero contribution (callers should default missing users to 0,
        except `days_since_last_txn` which already fills in the sentinel).

    Raises:
        KeyError: `metric` is not a registered builder name.
    """
    return await METRIC_BUILDERS[metric](
        session, tenant_id, txn_type=txn_type, window_days=window_days
    )
