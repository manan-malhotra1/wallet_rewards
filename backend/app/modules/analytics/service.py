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

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.schemas import (
    ActiveUsers,
    DashboardSummary,
    RevenueSlice,
    RewardsPoint,
    RewardsTimeseries,
    ScalarWithPrevious,
    ServiceSlice,
    StatusBucket,
    TimeseriesPoint,
    TransactionsTimeseries,
    UserPoint,
    UsersTimeseries,
)
from app.shared.exceptions import TenantNotFound
from app.shared.models import (
    REDEMPTION_STATUS_COMPLETED,
    REWARD_TYPE_POINTS,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    Redemption,
    RewardEvent,
    Rule,
    Tenant,
    Transaction,
    User,
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


async def _new_user_count(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> int:
    """Count users whose created_at falls inside the window."""
    stmt = select(func.count(User.id)).where(
        User.tenant_id == tenant_id,
        User.created_at >= window.start,
        User.created_at < window.end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def _distinct_transactors(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> int:
    """Distinct users who initiated a COMPLETED transaction in the window."""
    stmt = select(func.count(func.distinct(Transaction.initiated_by))).where(
        Transaction.tenant_id == tenant_id,
        Transaction.status == TXN_STATUS_COMPLETED,
        Transaction.initiated_by.is_not(None),
        Transaction.created_at >= window.start,
        Transaction.created_at < window.end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def _revenue_total(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> Decimal:
    """Sum of fee + tax + commission on COMPLETED transactions in the window."""
    stmt = select(
        func.coalesce(
            func.sum(
                Transaction.fee_amount
                + Transaction.tax_amount
                + Transaction.commission_amount
            ),
            0,
        )
    ).where(
        Transaction.tenant_id == tenant_id,
        Transaction.status == TXN_STATUS_COMPLETED,
        Transaction.created_at >= window.start,
        Transaction.created_at < window.end,
    )
    return Decimal((await session.execute(stmt)).scalar_one())


async def _points_issued(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> Decimal:
    """Points issued in the window (points-type RewardEvent rows).

    `reward_events` has no tenant_id column, so we scope by joining `rules`
    (which does) — mirrors budgets.service. Only `reward_type == 'points'`
    events count as points issuance; cashback rewards are excluded.
    """
    stmt = (
        select(func.coalesce(func.sum(RewardEvent.reward_value), 0))
        .join(Rule, Rule.id == RewardEvent.rule_id)
        .where(
            Rule.tenant_id == tenant_id,
            RewardEvent.reward_type == REWARD_TYPE_POINTS,
            RewardEvent.created_at >= window.start,
            RewardEvent.created_at < window.end,
        )
    )
    return Decimal((await session.execute(stmt)).scalar_one())


async def _points_redeemed(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> Decimal:
    """Points redeemed via COMPLETED redemptions in the window."""
    stmt = select(func.coalesce(func.sum(Redemption.points_amount), 0)).where(
        Redemption.tenant_id == tenant_id,
        Redemption.status == REDEMPTION_STATUS_COMPLETED,
        Redemption.created_at >= window.start,
        Redemption.created_at < window.end,
    )
    return Decimal((await session.execute(stmt)).scalar_one())


async def dashboard_summary(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    now: datetime | None = None,
) -> DashboardSummary:
    """All stat-tile scalars for the range, current + previous period.

    One round-trip populates the top tile row. Every scalar is tenant-scoped;
    `total_users` is all-time, `active_users_period` is distinct transactors in
    the current window.
    """
    await _assert_tenant_exists(session, tenant_id)
    current, previous = resolve_window(range_key, now=now)

    cur_count, cur_vol = await _txn_count_and_volume(session, tenant_id, current)
    prev_count, prev_vol = await _txn_count_and_volume(session, tenant_id, previous)

    cur_rev = await _revenue_total(session, tenant_id, current)
    prev_rev = await _revenue_total(session, tenant_id, previous)

    cur_new = await _new_user_count(session, tenant_id, current)
    prev_new = await _new_user_count(session, tenant_id, previous)

    cur_issued = await _points_issued(session, tenant_id, current)
    prev_issued = await _points_issued(session, tenant_id, previous)
    cur_redeemed = await _points_redeemed(session, tenant_id, current)
    prev_redeemed = await _points_redeemed(session, tenant_id, previous)

    total_users = int(
        (
            await session.execute(
                select(func.count(User.id)).where(User.tenant_id == tenant_id)
            )
        ).scalar_one()
    )
    active = await _distinct_transactors(session, tenant_id, current)

    def _avg(vol: Decimal, count: int) -> Decimal:
        return (vol / count) if count else Decimal(0)

    return DashboardSummary(
        transaction_count=ScalarWithPrevious(
            current=Decimal(cur_count), previous=Decimal(prev_count)
        ),
        transaction_volume=ScalarWithPrevious(current=cur_vol, previous=prev_vol),
        avg_transaction_value=ScalarWithPrevious(
            current=_avg(cur_vol, cur_count), previous=_avg(prev_vol, prev_count)
        ),
        revenue_total=ScalarWithPrevious(current=cur_rev, previous=prev_rev),
        new_users=ScalarWithPrevious(
            current=Decimal(cur_new), previous=Decimal(prev_new)
        ),
        total_users=Decimal(total_users),
        active_users_period=Decimal(active),
        points_issued=ScalarWithPrevious(current=cur_issued, previous=prev_issued),
        points_redeemed=ScalarWithPrevious(current=cur_redeemed, previous=prev_redeemed),
    )


async def transactions_by_service(
    session: AsyncSession, *, tenant_id: UUID, range_key: str, now: datetime | None = None
) -> list[ServiceSlice]:
    """COMPLETED transaction count + volume grouped by transaction_type.

    Row `count` is unpacked positionally — `Row.count` is a builtin method, so
    attribute access would collide (mypy) and shadow the labelled column.
    """
    await _assert_tenant_exists(session, tenant_id)
    current, _ = resolve_window(range_key, now=now)
    stmt = (
        select(
            Transaction.transaction_type.label("service_type"),
            func.count(Transaction.id).label("count"),
            func.coalesce(func.sum(Transaction.amount), 0).label("volume"),
        )
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.status == TXN_STATUS_COMPLETED,
            Transaction.created_at >= current.start,
            Transaction.created_at < current.end,
        )
        .group_by(Transaction.transaction_type)
        .order_by(func.count(Transaction.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        ServiceSlice(service_type=service_type, count=int(count), volume=Decimal(volume))
        for service_type, count, volume in rows
    ]


async def transactions_by_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> list[StatusBucket]:
    """Per-bucket completed/failed/pending counts (all statuses)."""
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)
    bucket = func.date_trunc(granularity, Transaction.created_at)
    stmt = (
        select(
            bucket.label("bucket"),
            func.sum(cast(Transaction.status == TXN_STATUS_COMPLETED, Integer)).label("completed"),
            func.sum(cast(Transaction.status == TXN_STATUS_FAILED, Integer)).label("failed"),
            func.sum(cast(Transaction.status == TXN_STATUS_PENDING, Integer)).label("pending"),
        )
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.created_at >= current.start,
            Transaction.created_at < current.end,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(stmt)).all()
    return [
        StatusBucket(
            bucket=bucket_val,
            completed=int(completed or 0),
            failed=int(failed or 0),
            pending=int(pending or 0),
        )
        for bucket_val, completed, failed, pending in rows
    ]


async def users_timeseries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> UsersTimeseries:
    """New-registration counts per bucket, current vs previous window."""
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, previous = resolve_window(range_key, now=now)

    async def _series(window: Window) -> list[UserPoint]:
        bucket = func.date_trunc(granularity, User.created_at)
        stmt = (
            select(bucket.label("bucket"), func.count(User.id).label("count"))
            .where(
                User.tenant_id == tenant_id,
                User.created_at >= window.start,
                User.created_at < window.end,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await session.execute(stmt)).all()
        return [UserPoint(bucket=bucket_val, count=int(count)) for bucket_val, count in rows]

    return UsersTimeseries(current=await _series(current), previous=await _series(previous))


async def active_users(
    session: AsyncSession, *, tenant_id: UUID, now: datetime | None = None
) -> ActiveUsers:
    """Distinct transactors over rolling 1/7/30-day windows + stickiness."""
    await _assert_tenant_exists(session, tenant_id)
    now = now or datetime.now(UTC)

    async def _distinct(days: int) -> int:
        window = Window(start=now - timedelta(days=days), end=now)
        return await _distinct_transactors(session, tenant_id, window)

    dau, wau, mau = await _distinct(1), await _distinct(7), await _distinct(30)
    stickiness = Decimal(dau) / Decimal(mau) if mau else Decimal(0)
    return ActiveUsers(dau=dau, wau=wau, mau=mau, stickiness=stickiness)


async def revenue_by_service(
    session: AsyncSession, *, tenant_id: UUID, range_key: str, now: datetime | None = None
) -> list[RevenueSlice]:
    """Fee/tax/commission/total grouped by transaction_type."""
    await _assert_tenant_exists(session, tenant_id)
    current, _ = resolve_window(range_key, now=now)
    stmt = (
        select(
            Transaction.transaction_type.label("service_type"),
            func.coalesce(func.sum(Transaction.fee_amount), 0).label("fee"),
            func.coalesce(func.sum(Transaction.tax_amount), 0).label("tax"),
            func.coalesce(func.sum(Transaction.commission_amount), 0).label("commission"),
        )
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.status == TXN_STATUS_COMPLETED,
            Transaction.created_at >= current.start,
            Transaction.created_at < current.end,
        )
        .group_by(Transaction.transaction_type)
    )
    rows = (await session.execute(stmt)).all()
    out: list[RevenueSlice] = []
    for service_type, fee, tax, comm in rows:
        fee_d, tax_d, comm_d = Decimal(fee), Decimal(tax), Decimal(comm)
        out.append(
            RevenueSlice(
                service_type=service_type,
                fee=fee_d,
                tax=tax_d,
                commission=comm_d,
                total=fee_d + tax_d + comm_d,
            )
        )
    return out


async def rewards_timeseries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> RewardsTimeseries:
    """Points issued vs redeemed per bucket + outstanding liability (all-time).

    Issuance scopes reward_events through `rules` (no tenant_id column of their
    own) and counts only `reward_type == 'points'`; redemptions filter on
    COMPLETED. Liability is all-time issued minus all-time redeemed.
    """
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)

    issued_bucket = func.date_trunc(granularity, RewardEvent.created_at)
    issued_stmt = (
        select(
            issued_bucket.label("bucket"),
            func.coalesce(func.sum(RewardEvent.reward_value), 0).label("v"),
        )
        .join(Rule, Rule.id == RewardEvent.rule_id)
        .where(
            Rule.tenant_id == tenant_id,
            RewardEvent.reward_type == REWARD_TYPE_POINTS,
            RewardEvent.created_at >= current.start,
            RewardEvent.created_at < current.end,
        )
        .group_by(issued_bucket)
    )
    redeemed_bucket = func.date_trunc(granularity, Redemption.created_at)
    redeemed_stmt = (
        select(
            redeemed_bucket.label("bucket"),
            func.coalesce(func.sum(Redemption.points_amount), 0).label("v"),
        )
        .where(
            Redemption.tenant_id == tenant_id,
            Redemption.status == REDEMPTION_STATUS_COMPLETED,
            Redemption.created_at >= current.start,
            Redemption.created_at < current.end,
        )
        .group_by(redeemed_bucket)
    )
    issued = {row.bucket: Decimal(row.v) for row in (await session.execute(issued_stmt)).all()}
    redeemed = {row.bucket: Decimal(row.v) for row in (await session.execute(redeemed_stmt)).all()}
    buckets = sorted(set(issued) | set(redeemed))
    points = [
        RewardsPoint(
            bucket=b,
            issued=issued.get(b, Decimal(0)),
            redeemed=redeemed.get(b, Decimal(0)),
        )
        for b in buckets
    ]

    total_issued = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(RewardEvent.reward_value), 0))
                .join(Rule, Rule.id == RewardEvent.rule_id)
                .where(
                    Rule.tenant_id == tenant_id,
                    RewardEvent.reward_type == REWARD_TYPE_POINTS,
                )
            )
        ).scalar_one()
    )
    total_redeemed = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(Redemption.points_amount), 0)).where(
                    Redemption.tenant_id == tenant_id,
                    Redemption.status == REDEMPTION_STATUS_COMPLETED,
                )
            )
        ).scalar_one()
    )
    return RewardsTimeseries(points=points, outstanding_liability=total_issued - total_redeemed)
