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

from sqlalchemy import ColumnElement, Integer, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.analytics.schemas import (
    ActiveUsers,
    BucketAmount,
    CountPoint,
    CountSeries,
    CurrencyInfo,
    CurrencyLiquidity,
    CurrencyScalar,
    CurrencySeries,
    DashboardSummary,
    MetricsTimeseries,
    NetFlowPoint,
    RevenueServiceSlice,
    RewardsPoint,
    RewardsTimeseries,
    ScalarWithPrevious,
    ServiceSlice,
    StatusBucket,
    UserPoint,
    UsersTimeseries,
    UserTypeSlice,
)
from app.modules.ledger.service import signed_balance_expr
from app.shared.exceptions import InvalidAnalyticsParameter, TenantNotFound
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_OPERATOR_ADJUSTMENT,
    ACCOUNT_TYPE_SYSTEM_CASH_INFLOW,
    ENTRY_CREDIT,
    ENTRY_DEBIT,
    ENTRY_STATUS_COMPLETED,
    INSTRUMENT_STATUS_ACTIVE,
    REWARD_TYPE_POINTS,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    Account,
    Instrument,
    InternalRedemption,
    LedgerEntry,
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
    """Return the granularity unchanged, or raise if unknown.

    Guards the `date_trunc` argument — never interpolate an unvalidated
    string into a SQL function.

    Raises:
        InvalidAnalyticsParameter: granularity is not recognised (HTTP 422).
    """
    if granularity not in _GRANULARITIES:
        raise InvalidAnalyticsParameter(f"unknown granularity: {granularity}")
    return granularity


def resolve_window(range_key: str, *, now: datetime | None = None) -> tuple[Window, Window]:
    """Derive the current window and the equal-length preceding window.

    Args:
        range_key: one of 24h / 7d / 30d / quarter.
        now: injectable clock for tests; defaults to current UTC time.

    Returns:
        (current, previous) — previous.end == current.start.

    Raises:
        InvalidAnalyticsParameter: range_key is not recognised (HTTP 422).
    """
    if range_key not in _RANGE_DAYS:
        raise InvalidAnalyticsParameter(f"unknown range: {range_key}")
    now = now or datetime.now(UTC)
    days = _RANGE_DAYS[range_key]
    span = timedelta(days=days)
    current = Window(start=now - span, end=now)
    previous = Window(start=current.start - span, end=current.start)
    return current, previous


def _utc_key(dt: datetime) -> datetime:
    """Normalise a datetime to naive-UTC for equality-safe dict keying.

    PG may hand back a bucket with a subtly different tz representation than the
    generated bucket starts; converting both to naive-UTC makes them compare
    equal. Naive datetimes are assumed to already be UTC.
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.replace(tzinfo=None)


def _bucket_starts(window: Window, granularity: str) -> list[datetime]:
    """Ordered date_trunc-aligned bucket starts covering [window.start, window.end).

    Mirrors Postgres date_trunc boundaries so zero-filled buckets line up with
    the grouped SQL rows. day -> midnight; week -> Monday 00:00; month -> 1st 00:00.

    Assumes the DB session is UTC: the windows are tz-aware UTC (resolve_window
    uses datetime.now(UTC)), and `_trunc` preserves that tzinfo via `.replace(...)`
    so the generated starts match Postgres `date_trunc` on a UTC timestamptz.
    """

    def _trunc(dt: datetime) -> datetime:
        d = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        if granularity == "week":
            d = d - timedelta(days=d.weekday())  # back to Monday (ISO, matches PG default)
        elif granularity == "month":
            d = d.replace(day=1)
        return d

    def _next(dt: datetime) -> datetime:
        if granularity == "day":
            return dt + timedelta(days=1)
        if granularity == "week":
            return dt + timedelta(weeks=1)
        # month
        return (dt.replace(day=1) + timedelta(days=32)).replace(day=1)

    out: list[datetime] = []
    cur = _trunc(window.start)
    while cur < window.end:
        out.append(cur)
        cur = _next(cur)
    return out


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Reject unknown tenants — same guard used across modules."""
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def list_currencies(session: AsyncSession, *, tenant_id: UUID) -> list[CurrencyInfo]:
    """Return the tenant's spendable currencies (money instruments) for the toggle.

    A MONEY currency is an active, non-deleted `Instrument` whose `account_type`
    is `financial_wallet` — the account kind auto-provisioned for holding fiat
    balance. Points units (`account_type == 'points_account'`) are deliberately
    excluded: they are a reward unit, not a spendable currency, and never appear
    in the money-metric currency toggle. Ordered by code for a stable toggle.

    Raises:
        TenantNotFound: tenant_id does not exist (HTTP 404).
    """
    await _assert_tenant_exists(session, tenant_id)
    stmt = (
        select(Instrument)
        .where(
            Instrument.tenant_id == tenant_id,
            Instrument.status == INSTRUMENT_STATUS_ACTIVE,
            Instrument.deleted_at.is_(None),
            Instrument.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
        )
        .order_by(Instrument.code)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [CurrencyInfo(code=i.code, symbol=i.symbol, display_name=i.display_name) for i in rows]


async def _txn_by_currency(
    session: AsyncSession, tenant_id: UUID, window: Window
) -> dict[str, tuple[int, Decimal, Decimal]]:
    """Per-currency COMPLETED (count, volume, fee) for a tenant/window.

    Grouped by `Transaction.currency` — money is NEVER summed across currencies
    (invariant: ZAR and MGA share no denominator). Returns a mapping
    currency -> (count, SUM(amount), SUM(fee_amount)). Unpacked positionally to
    avoid the `Row.count` builtin-method collision.
    """
    stmt = (
        select(
            Transaction.currency,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
            func.coalesce(func.sum(Transaction.fee_amount), 0),
        )
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.status == TXN_STATUS_COMPLETED,
            Transaction.created_at >= window.start,
            Transaction.created_at < window.end,
        )
        .group_by(Transaction.currency)
    )
    rows = (await session.execute(stmt)).all()
    return {
        currency: (int(count), Decimal(volume), Decimal(fee))
        for currency, count, volume, fee in rows
    }


def _build_currency_series(
    cur_map: dict[str, dict[datetime, Decimal]],
    prev_map: dict[str, dict[datetime, Decimal]],
    cur_starts: list[datetime],
    prev_starts: list[datetime],
) -> list[CurrencySeries]:
    """Assemble one dense CurrencySeries per currency present in either window.

    Zero-fills each currency's buckets so `current` / `previous` are dense and
    aligned to the generated bucket starts. Buckets are keyed by naive-UTC so a
    subtly different PG tz representation still matches. Currencies ordered by
    code for a stable render.
    """
    currencies = sorted(set(cur_map) | set(prev_map))
    out: list[CurrencySeries] = []
    for currency in currencies:
        cur_b = cur_map.get(currency, {})
        prev_b = prev_map.get(currency, {})
        current = [
            BucketAmount(bucket=start, value=cur_b.get(_utc_key(start), Decimal(0)))
            for start in cur_starts
        ]
        previous = [
            BucketAmount(bucket=start, value=prev_b.get(_utc_key(start), Decimal(0)))
            for start in prev_starts
        ]
        out.append(CurrencySeries(currency=currency, current=current, previous=previous))
    return out


async def metrics_timeseries(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> MetricsTimeseries:
    """Trend data: agnostic COMPLETED count + per-currency volume & revenue.

    `count` is a single currency-agnostic dense series (current + aligned
    previous). `volume` (SUM amount) and `revenue` (SUM fee) are each a list of
    per-currency dense series — money is NEVER summed across currencies. Every
    series zero-fills empty buckets so `current[i]` / `previous[i]` share the
    same relative offset for the overlay.
    """
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, previous = resolve_window(range_key, now=now)
    cur_starts = _bucket_starts(current, granularity)
    prev_starts = _bucket_starts(previous, granularity)

    async def _count_series(window: Window, starts: list[datetime]) -> list[CountPoint]:
        bucket = func.date_trunc(granularity, Transaction.created_at)
        stmt = (
            select(bucket, func.count(Transaction.id))
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.status == TXN_STATUS_COMPLETED,
                Transaction.created_at >= window.start,
                Transaction.created_at < window.end,
            )
            .group_by(bucket)
        )
        rows = (await session.execute(stmt)).all()
        by_bucket = {_utc_key(bucket_val): int(count) for bucket_val, count in rows}
        return [
            CountPoint(bucket=start, count=by_bucket.get(_utc_key(start), 0)) for start in starts
        ]

    async def _money_by_currency(
        window: Window, column: InstrumentedAttribute[float]
    ) -> dict[str, dict[datetime, Decimal]]:
        """Bucketed SUM(column) grouped by (currency, bucket) for the window."""
        bucket = func.date_trunc(granularity, Transaction.created_at)
        stmt = (
            select(Transaction.currency, bucket, func.coalesce(func.sum(column), 0))
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.status == TXN_STATUS_COMPLETED,
                Transaction.created_at >= window.start,
                Transaction.created_at < window.end,
            )
            .group_by(Transaction.currency, bucket)
        )
        rows = (await session.execute(stmt)).all()
        out: dict[str, dict[datetime, Decimal]] = {}
        for currency, bucket_val, value in rows:
            out.setdefault(currency, {})[_utc_key(bucket_val)] = Decimal(value)
        return out

    count = CountSeries(
        current=await _count_series(current, cur_starts),
        previous=await _count_series(previous, prev_starts),
    )
    volume = _build_currency_series(
        await _money_by_currency(current, Transaction.amount),
        await _money_by_currency(previous, Transaction.amount),
        cur_starts,
        prev_starts,
    )
    revenue = _build_currency_series(
        await _money_by_currency(current, Transaction.fee_amount),
        await _money_by_currency(previous, Transaction.fee_amount),
        cur_starts,
        prev_starts,
    )
    return MetricsTimeseries(count=count, volume=volume, revenue=revenue)


async def _new_user_count(session: AsyncSession, tenant_id: UUID, window: Window) -> int:
    """Count users whose created_at falls inside the window."""
    stmt = select(func.count(User.id)).where(
        User.tenant_id == tenant_id,
        User.created_at >= window.start,
        User.created_at < window.end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def _distinct_transactors(session: AsyncSession, tenant_id: UUID, window: Window) -> int:
    """Distinct users who initiated a COMPLETED transaction in the window."""
    stmt = select(func.count(func.distinct(Transaction.initiated_by))).where(
        Transaction.tenant_id == tenant_id,
        Transaction.status == TXN_STATUS_COMPLETED,
        Transaction.initiated_by.is_not(None),
        Transaction.created_at >= window.start,
        Transaction.created_at < window.end,
    )
    return int((await session.execute(stmt)).scalar_one())


async def _points_issued(session: AsyncSession, tenant_id: UUID, window: Window) -> Decimal:
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


async def _points_redeemed(session: AsyncSession, tenant_id: UUID, window: Window) -> Decimal:
    """Points redeemed into customer wallets in the window.

    Internal redemptions settle synchronously, so every row is a completed one
    and no status filter is needed.
    """
    stmt = select(func.coalesce(func.sum(InternalRedemption.points_amount), 0)).where(
        InternalRedemption.tenant_id == tenant_id,
        InternalRedemption.created_at >= window.start,
        InternalRedemption.created_at < window.end,
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

    # Per-currency (count, volume, fee) — money is NEVER summed across currencies.
    cur_by_ccy = await _txn_by_currency(session, tenant_id, current)
    prev_by_ccy = await _txn_by_currency(session, tenant_id, previous)

    cur_new = await _new_user_count(session, tenant_id, current)
    prev_new = await _new_user_count(session, tenant_id, previous)

    cur_issued = await _points_issued(session, tenant_id, current)
    prev_issued = await _points_issued(session, tenant_id, previous)
    cur_redeemed = await _points_redeemed(session, tenant_id, current)
    prev_redeemed = await _points_redeemed(session, tenant_id, previous)

    total_users = int(
        (
            await session.execute(select(func.count(User.id)).where(User.tenant_id == tenant_id))
        ).scalar_one()
    )
    active = await _distinct_transactors(session, tenant_id, current)

    # transaction_count stays currency-agnostic: sum the per-currency counts.
    cur_count = sum(c for c, _, _ in cur_by_ccy.values())
    prev_count = sum(c for c, _, _ in prev_by_ccy.values())

    def _avg(vol: Decimal, count: int) -> Decimal:
        return (vol / count) if count else Decimal(0)

    # One CurrencyScalar per currency with activity in EITHER window.
    currencies = sorted(set(cur_by_ccy) | set(prev_by_ccy))
    volume: list[CurrencyScalar] = []
    avg: list[CurrencyScalar] = []
    revenue: list[CurrencyScalar] = []
    for ccy in currencies:
        c_count, c_vol, c_fee = cur_by_ccy.get(ccy, (0, Decimal(0), Decimal(0)))
        p_count, p_vol, p_fee = prev_by_ccy.get(ccy, (0, Decimal(0), Decimal(0)))
        volume.append(CurrencyScalar(currency=ccy, current=c_vol, previous=p_vol))
        avg.append(
            CurrencyScalar(
                currency=ccy, current=_avg(c_vol, c_count), previous=_avg(p_vol, p_count)
            )
        )
        revenue.append(CurrencyScalar(currency=ccy, current=c_fee, previous=p_fee))

    return DashboardSummary(
        transaction_count=ScalarWithPrevious(
            current=Decimal(cur_count), previous=Decimal(prev_count)
        ),
        transaction_volume=volume,
        avg_transaction_value=avg,
        revenue_total=revenue,
        new_users=ScalarWithPrevious(current=Decimal(cur_new), previous=Decimal(prev_new)),
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
    """New-registration counts per bucket, current vs previous window.

    Zero-fills every empty bucket so both series are DENSE and equal-length:
    `current[i]` and `previous[i]` share the same relative offset, which the
    previous-period overlay aligns on.
    """
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
        # Unpack positionally — `Row.count` is a builtin method, so attribute
        # access would collide (mypy) and shadow the labelled column.
        by_bucket = {_utc_key(bucket_val): int(count) for bucket_val, count in rows}
        return [
            UserPoint(bucket=start, count=by_bucket.get(_utc_key(start), 0))
            for start in _bucket_starts(window, granularity)
        ]

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
) -> list[RevenueServiceSlice]:
    """Charges breakdown grouped by (transaction_type, currency); total = revenue.

    Grouped by currency as well as service — money is NEVER summed across
    currencies. `total` reflects operator revenue, which is the fee only — tax
    is a pass-through and commission is an agent cost, so neither is revenue. The
    `fee`, `tax` and `commission` component fields remain a full per-currency
    charges breakdown for the row. Ordered by service then currency.
    """
    await _assert_tenant_exists(session, tenant_id)
    current, _ = resolve_window(range_key, now=now)
    stmt = (
        select(
            Transaction.transaction_type.label("service_type"),
            Transaction.currency.label("currency"),
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
        .group_by(Transaction.transaction_type, Transaction.currency)
        .order_by(Transaction.transaction_type, Transaction.currency)
    )
    rows = (await session.execute(stmt)).all()
    out: list[RevenueServiceSlice] = []
    for service_type, currency, fee, tax, comm in rows:
        fee_d, tax_d, comm_d = Decimal(fee), Decimal(tax), Decimal(comm)
        out.append(
            RevenueServiceSlice(
                service_type=service_type,
                currency=currency,
                fee=fee_d,
                tax=tax_d,
                commission=comm_d,
                total=fee_d,
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
    redeemed_bucket = func.date_trunc(granularity, InternalRedemption.created_at)
    redeemed_stmt = (
        select(
            redeemed_bucket.label("bucket"),
            func.coalesce(func.sum(InternalRedemption.points_amount), 0).label("v"),
        )
        .where(
            InternalRedemption.tenant_id == tenant_id,
            InternalRedemption.created_at >= current.start,
            InternalRedemption.created_at < current.end,
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
                select(func.coalesce(func.sum(InternalRedemption.points_amount), 0)).where(
                    InternalRedemption.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
    )
    return RewardsTimeseries(points=points, outstanding_liability=total_issued - total_redeemed)


def _signed_balance_expr() -> ColumnElement[Decimal]:
    """SQL expression: SUM(CREDIT) - SUM(DEBIT) over COMPLETED ledger entries.

    Balance for an account is credits minus debits (ledger invariant). The
    caller must already filter to COMPLETED status and the target account set.

    Thin wrapper kept so this module's call sites don't change — the actual
    signed-amount formula is the single shared `ledger.service.signed_balance_expr`
    (also used by `sum_completed_balance` and the segment metric registry's
    `_balance` builder), so a future ledger-schema change is a one-line edit.
    """
    return func.coalesce(func.sum(signed_balance_expr()), 0)


async def _account_type_balance_by_currency(
    session: AsyncSession, tenant_id: UUID, account_type: str
) -> dict[str, Decimal]:
    """Net COMPLETED balance per currency across all accounts of a type.

    Grouped by `ledger_entries.currency` — balances are NEVER summed across
    currencies.

    Args:
        account_type: e.g. `financial_wallet` (user float) or
            `system_cash_inflow` (operator cash float).

    Returns:
        Mapping currency -> signed Decimal balance (credits minus debits).
    """
    stmt = (
        select(LedgerEntry.currency, _signed_balance_expr())
        .select_from(LedgerEntry)
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
        .group_by(LedgerEntry.currency)
    )
    rows = (await session.execute(stmt)).all()
    return {currency: Decimal(balance) for currency, balance in rows}


async def liquidity(session: AsyncSession, *, tenant_id: UUID) -> list[CurrencyLiquidity]:
    """Per-currency wallet float liability + cash-float balance (point in time).

    `wallet_liability` is the signed balance across user `financial_wallet`
    accounts for that currency — money the operator owes users.
    `cash_float_balance` is the `system_cash_inflow` balance for that currency.
    One row per currency present in either set; balances are NEVER summed across
    currencies. Ordered by currency.
    """
    await _assert_tenant_exists(session, tenant_id)
    wallet = await _account_type_balance_by_currency(
        session, tenant_id, ACCOUNT_TYPE_FINANCIAL_WALLET
    )
    cash = await _account_type_balance_by_currency(
        session, tenant_id, ACCOUNT_TYPE_SYSTEM_CASH_INFLOW
    )
    currencies = sorted(set(wallet) | set(cash))
    return [
        CurrencyLiquidity(
            currency=currency,
            wallet_liability=wallet.get(currency, Decimal(0)),
            cash_float_balance=cash.get(currency, Decimal(0)),
        )
        for currency in currencies
    ]


async def net_flow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> list[NetFlowPoint]:
    """Per-bucket, per-currency wallet flow plus operator treasury flow.

    Buckets COMPLETED ledger entries by date_trunc(granularity, created_at) AND
    currency — money is NEVER summed across currencies. Two independent pairs are
    returned per bucket (see `NetFlowPoint`):

    * wallet `inflow` / `outflow` — CREDIT / DEBIT legs on `financial_wallet`
      accounts, i.e. money crossing the user-wallet boundary.
    * `treasury_inflow` / `treasury_outflow` — operator cash moving between the
      cash float and the bank, measured on the `operator_adjustment` bank-mirror
      leg: a DEBIT there means cash came FROM the bank into the float (inflow), a
      CREDIT means cash went back TO the bank (outflow).

    The bank-mirror leg is the right place to measure operator movement. Reading
    the float leg instead would also catch `fund_user` (which debits the float to
    credit a customer) and report internal funding as money leaving the platform.
    """
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)
    bucket = func.date_trunc(granularity, LedgerEntry.created_at)
    credit = cast(LedgerEntry.entry_type == ENTRY_CREDIT, Integer) * LedgerEntry.amount
    debit = cast(LedgerEntry.entry_type == ENTRY_DEBIT, Integer) * LedgerEntry.amount

    def flow_stmt(account_type: str) -> Select[tuple[datetime, str, Decimal, Decimal]]:
        """Bucketed CREDIT/DEBIT totals for one account type in the window."""
        return (
            select(
                bucket.label("bucket"),
                LedgerEntry.currency.label("currency"),
                func.coalesce(func.sum(credit), 0).label("credit_total"),
                func.coalesce(func.sum(debit), 0).label("debit_total"),
            )
            .select_from(LedgerEntry)
            .join(Account, Account.id == LedgerEntry.account_id)
            .where(
                Account.tenant_id == tenant_id,
                Account.account_type == account_type,
                LedgerEntry.status == ENTRY_STATUS_COMPLETED,
                LedgerEntry.created_at >= current.start,
                LedgerEntry.created_at < current.end,
            )
            .group_by(bucket, LedgerEntry.currency)
            .order_by(bucket, LedgerEntry.currency)
        )

    wallet_rows = (await session.execute(flow_stmt(ACCOUNT_TYPE_FINANCIAL_WALLET))).all()
    treasury_rows = (await session.execute(flow_stmt(ACCOUNT_TYPE_OPERATOR_ADJUSTMENT))).all()

    # Merge on (bucket, currency): a bucket may have treasury movement with no
    # customer activity (or the reverse), and both must still surface.
    merged: dict[tuple[datetime, str], dict[str, Decimal]] = {}
    for bucket_val, currency, credit_total, debit_total in wallet_rows:
        merged[(bucket_val, currency)] = {
            "inflow": Decimal(credit_total),
            "outflow": Decimal(debit_total),
            "treasury_inflow": Decimal(0),
            "treasury_outflow": Decimal(0),
        }
    for bucket_val, currency, credit_total, debit_total in treasury_rows:
        entry = merged.setdefault(
            (bucket_val, currency),
            {
                "inflow": Decimal(0),
                "outflow": Decimal(0),
                "treasury_inflow": Decimal(0),
                "treasury_outflow": Decimal(0),
            },
        )
        # DEBIT on the bank mirror = cash drawn from the bank into the float.
        entry["treasury_inflow"] = Decimal(debit_total)
        entry["treasury_outflow"] = Decimal(credit_total)

    return [
        NetFlowPoint(
            bucket=bucket_val,
            currency=currency,
            inflow=values["inflow"],
            outflow=values["outflow"],
            treasury_inflow=values["treasury_inflow"],
            treasury_outflow=values["treasury_outflow"],
        )
        for (bucket_val, currency), values in sorted(
            merged.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]


async def users_by_type(session: AsyncSession, *, tenant_id: UUID) -> list[UserTypeSlice]:
    """Distribution of users across user_type (consumer/agent/merchant…).

    Row `count` is unpacked positionally — `Row.count` is a builtin method, so
    attribute access would collide and shadow the labelled column.
    """
    await _assert_tenant_exists(session, tenant_id)
    stmt = (
        select(User.user_type.label("user_type"), func.count(User.id).label("count"))
        .where(User.tenant_id == tenant_id)
        .group_by(User.user_type)
        .order_by(func.count(User.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [UserTypeSlice(user_type=user_type, count=int(count)) for user_type, count in rows]
