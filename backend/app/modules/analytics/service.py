"""Analytics service — tenant-scoped read aggregations for the dashboard.

Pure aggregation over existing tables via SQLAlchemy. No writes. Every query
filters by tenant_id (invariant 7). `resolve_window` derives the current and
previous comparison windows; `date_trunc` buckets the series.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.schemas import (
    TimeseriesPoint,
    TransactionsTimeseries,
)
from app.shared.exceptions import TenantNotFound
from app.shared.models import (
    TXN_STATUS_COMPLETED,
    Tenant,
    Transaction,
)

# Allowed query values — fail closed on anything else.
_RANGE_DAYS = {"24h": 1, "7d": 7, "30d": 30, "quarter": 90}
_GRANULARITIES = {"day", "week", "month"}


@dataclass(frozen=True)
class Window:
    """A half-open [start, end) time window."""

    start: datetime
    end: datetime


def validate_granularity(granularity: str) -> str:
    """Return the granularity unchanged, or raise ValueError if unknown.

    Guards the `date_trunc` argument — never interpolate an unvalidated
    string into a SQL function.
    """
    if granularity not in _GRANULARITIES:
        raise ValueError(f"unknown granularity: {granularity}")
    return granularity


def resolve_window(range_key: str, *, now: datetime | None = None) -> tuple[Window, Window]:
    """Derive the current window and the equal-length preceding window.

    Args:
        range_key: one of 24h / 7d / 30d / quarter.
        now: injectable clock for tests; defaults to current UTC time.

    Returns:
        (current, previous) — previous.end == current.start.

    Raises:
        ValueError: range_key is not recognised.
    """
    if range_key not in _RANGE_DAYS:
        raise ValueError(f"unknown range: {range_key}")
    now = now or datetime.now(UTC)
    days = _RANGE_DAYS[range_key]
    span = timedelta(days=days)
    current = Window(start=now - span, end=now)
    previous = Window(start=current.start - span, end=current.start)
    return current, previous


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject unknown tenants — same guard used across modules."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def _txn_count_and_volume(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> tuple[int, Decimal]:
    """COMPLETED transaction count and summed amount for a tenant/window."""
    stmt = select(
        func.count(Transaction.id),
        func.coalesce(func.sum(Transaction.amount), 0),
    ).where(
        Transaction.tenant_id == tenant_id,
        Transaction.status == TXN_STATUS_COMPLETED,
        Transaction.created_at >= window.start,
        Transaction.created_at < window.end,
    )
    count, volume = (await session.execute(stmt)).one()
    return int(count), Decimal(volume)


async def transactions_timeseries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> TransactionsTimeseries:
    """Bucketed COMPLETED transaction count + volume, current vs previous.

    Groups by date_trunc(granularity, created_at). Buckets with no rows are
    simply absent (the frontend fills gaps); both series share the granularity.
    """
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, previous = resolve_window(range_key, now=now)

    async def _series(window: Window) -> list[TimeseriesPoint]:
        bucket = func.date_trunc(granularity, Transaction.created_at)
        stmt = (
            select(
                bucket.label("bucket"),
                func.count(Transaction.id).label("count"),
                func.coalesce(func.sum(Transaction.amount), 0).label("volume"),
            )
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.status == TXN_STATUS_COMPLETED,
                Transaction.created_at >= window.start,
                Transaction.created_at < window.end,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await session.execute(stmt)).all()
        return [
            TimeseriesPoint(bucket=bucket_val, count=int(count), volume=Decimal(volume))
            for bucket_val, count, volume in rows
        ]

    return TransactionsTimeseries(current=await _series(current), previous=await _series(previous))
