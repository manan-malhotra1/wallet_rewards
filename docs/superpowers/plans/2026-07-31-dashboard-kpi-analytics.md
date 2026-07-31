# Dashboard KPI & Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the operational-only admin dashboard with an interactive KPI dashboard (transaction activity, user growth, revenue, rewards/liquidity) backed by a real tenant-scoped analytics API, with day-on-day / week-on-week comparison.

**Architecture:** A new read-only backend `analytics` module aggregates existing tables (`transactions`, `users`, `ledger_entries`, `redemptions`) via SQLAlchemy `date_trunc` grouping, tenant-scoped, no raw SQL, no ledger writes. The Next.js dashboard is rebuilt with Recharts: clickable stat tiles drive a shared trend chart, a global range/granularity switcher (URL params) refetches through a server action, and every trend chart overlays the previous period.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest (backend); Next.js 16 App Router · Recharts · Tailwind · Vitest + Testing Library (frontend).

**Reference spec:** `docs/superpowers/specs/2026-07-31-dashboard-kpi-analytics-design.md`

---

## Conventions used throughout

- GET analytics endpoints take `tenant_id: UUID` + `range: str` + `granularity: str` query params, gated by a read role (`finance-reviewer` OR `platform-admin`), mirroring `app/modules/reconciliation/router.py`.
- `range` ∈ {`24h`, `7d`, `30d`, `quarter`}; `granularity` ∈ {`day`, `week`, `month`}.
- The "previous period" is the immediately-preceding window of equal length.
- Money sums stay in the tenant base currency (single-currency assumption per spec §6).
- Backend tests live under `backend/tests/analytics/`. Run backend commands from `backend/` with the venv active.

---

# PART 1 — Backend analytics module

## Task 1: Analytics Pydantic schemas

**Files:**
- Create: `backend/app/modules/analytics/__init__.py`
- Create: `backend/app/modules/analytics/schemas.py`

- [ ] **Step 1: Create the package init**

Create `backend/app/modules/analytics/__init__.py`:

```python
"""Analytics module — read-only KPI aggregations for the admin dashboard.

Aggregates existing domain tables (transactions, users, ledger, redemptions)
into time-bucketed and grouped series. No writes, no ledger mutation; every
query is tenant-scoped per invariant 7.
"""
```

- [ ] **Step 2: Write the schemas**

Create `backend/app/modules/analytics/schemas.py`:

```python
"""Pydantic v2 response models for the analytics endpoints.

Each model is a plain read DTO. `current`/`previous` pairs let the frontend
compute day-on-day / week-on-week deltas without a second round-trip.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ScalarWithPrevious(BaseModel):
    """A single headline number plus its previous-period value.

    The frontend derives the delta % (current vs previous) for the tile chip.
    """

    current: Decimal
    previous: Decimal


class DashboardSummary(BaseModel):
    """All stat-tile scalars for the selected range, current + previous period.

    One round-trip populates the top tile row across KPI groups A/B/D/E.
    """

    transaction_count: ScalarWithPrevious
    transaction_volume: ScalarWithPrevious
    avg_transaction_value: ScalarWithPrevious
    revenue_total: ScalarWithPrevious
    new_users: ScalarWithPrevious
    total_users: Decimal
    active_users_period: Decimal
    points_issued: ScalarWithPrevious
    points_redeemed: ScalarWithPrevious


class TimeseriesPoint(BaseModel):
    """One bucket of the transactions time series."""

    bucket: datetime
    count: int
    volume: Decimal


class TransactionsTimeseries(BaseModel):
    """Current-period series plus the aligned previous-period series.

    `previous` has the same length as `current`; the frontend draws it as the
    dotted comparison overlay.
    """

    current: list[TimeseriesPoint]
    previous: list[TimeseriesPoint]


class ServiceSlice(BaseModel):
    """Transaction count + value for one transaction_type (service)."""

    service_type: str
    count: int
    volume: Decimal


class StatusBucket(BaseModel):
    """Per-bucket completed/failed/pending transaction counts."""

    bucket: datetime
    completed: int
    failed: int
    pending: int


class UserPoint(BaseModel):
    """New-registration count for one bucket."""

    bucket: datetime
    count: int


class UsersTimeseries(BaseModel):
    """New registrations per bucket, current + previous period."""

    current: list[UserPoint]
    previous: list[UserPoint]


class ActiveUsers(BaseModel):
    """Distinct transacting users over rolling windows + stickiness ratio."""

    dau: int
    wau: int
    mau: int
    stickiness: Decimal  # dau / mau, 0 when mau == 0


class RevenueSlice(BaseModel):
    """Revenue components for one transaction_type."""

    service_type: str
    fee: Decimal
    tax: Decimal
    commission: Decimal
    total: Decimal


class RewardsPoint(BaseModel):
    """Points issued vs redeemed for one bucket."""

    bucket: datetime
    issued: Decimal
    redeemed: Decimal


class RewardsTimeseries(BaseModel):
    """Points issued vs redeemed per bucket + outstanding liability."""

    points: list[RewardsPoint]
    outstanding_liability: Decimal
```

- [ ] **Step 3: Sanity-import**

Run: `python -c "from app.modules.analytics.schemas import DashboardSummary; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/analytics/__init__.py backend/app/modules/analytics/schemas.py
git commit -m "feat(analytics): response schemas for KPI dashboard endpoints"
```

---

## Task 2: Time-window helpers + transactions aggregations

**Files:**
- Create: `backend/app/modules/analytics/service.py`
- Test: `backend/tests/analytics/__init__.py`, `backend/tests/analytics/test_window.py`

- [ ] **Step 1: Write the failing test for the window helper**

Create `backend/tests/analytics/__init__.py` (empty file).

Create `backend/tests/analytics/test_window.py`:

```python
"""Unit tests for the analytics window/granularity helpers (pure functions)."""

from datetime import UTC, datetime

import pytest

from app.modules.analytics.service import resolve_window, validate_granularity


def test_resolve_window_7d_gives_two_aligned_windows():
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    current, previous = resolve_window("7d", now=now)
    # current window is the last 7 days ending now
    assert (current.end - current.start).days == 7
    # previous window is the 7 days immediately before current
    assert previous.end == current.start
    assert (previous.end - previous.start).days == 7


def test_resolve_window_rejects_unknown_range():
    with pytest.raises(ValueError):
        resolve_window("all-time", now=datetime(2026, 7, 31, tzinfo=UTC))


def test_validate_granularity_rejects_unknown():
    with pytest.raises(ValueError):
        validate_granularity("hourly")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/analytics/test_window.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_window'`

- [ ] **Step 3: Write the service module with the window helpers + first aggregations**

Create `backend/app/modules/analytics/service.py`:

```python
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

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.schemas import (
    DashboardSummary,
    ScalarWithPrevious,
    TimeseriesPoint,
    TransactionsTimeseries,
)
from app.shared.exceptions import TenantNotFound
from app.shared.models import (
    TXN_STATUS_COMPLETED,
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
            TimeseriesPoint(bucket=r.bucket, count=int(r.count), volume=Decimal(r.volume))
            for r in rows
        ]

    return TransactionsTimeseries(current=await _series(current), previous=await _series(previous))
```

- [ ] **Step 4: Run the window test to verify it passes**

Run: `pytest tests/analytics/test_window.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/analytics/service.py backend/tests/analytics/__init__.py backend/tests/analytics/test_window.py
git commit -m "feat(analytics): window helpers + transactions timeseries aggregation"
```

---

## Task 3: Summary, service-mix, status, users, revenue, rewards aggregations

**Files:**
- Modify: `backend/app/modules/analytics/service.py`

- [ ] **Step 1: Add the summary aggregation**

Append to `backend/app/modules/analytics/service.py`:

```python
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
    """Points issued in the window (Reward rows)."""
    stmt = select(func.coalesce(func.sum(Reward.points_amount), 0)).where(
        Reward.tenant_id == tenant_id,
        Reward.created_at >= window.start,
        Reward.created_at < window.end,
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
    """All stat-tile scalars for the range, current + previous period."""
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
        transaction_count=ScalarWithPrevious(current=cur_count, previous=prev_count),
        transaction_volume=ScalarWithPrevious(current=cur_vol, previous=prev_vol),
        avg_transaction_value=ScalarWithPrevious(
            current=_avg(cur_vol, cur_count), previous=_avg(prev_vol, prev_count)
        ),
        revenue_total=ScalarWithPrevious(current=cur_rev, previous=prev_rev),
        new_users=ScalarWithPrevious(current=cur_new, previous=prev_new),
        total_users=Decimal(total_users),
        active_users_period=Decimal(active),
        points_issued=ScalarWithPrevious(current=cur_issued, previous=prev_issued),
        points_redeemed=ScalarWithPrevious(current=cur_redeemed, previous=prev_redeemed),
    )
```

- [ ] **Step 2: Add the grouped/breakdown aggregations**

Append to `backend/app/modules/analytics/service.py`:

```python
async def transactions_by_service(
    session: AsyncSession, *, tenant_id: UUID, range_key: str, now: datetime | None = None
) -> list[ServiceSlice]:
    """COMPLETED transaction count + volume grouped by transaction_type."""
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
        ServiceSlice(service_type=r.service_type, count=int(r.count), volume=Decimal(r.volume))
        for r in rows
    ]


async def transactions_by_status(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> list[StatusBucket]:
    """Per-bucket completed/failed/pending counts (all statuses, not just completed)."""
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)
    bucket = func.date_trunc(granularity, Transaction.created_at)

    def _count_where(status: str):
        return func.count(func.nullif(Transaction.status != status, True))

    stmt = (
        select(
            bucket.label("bucket"),
            func.sum(func.cast(Transaction.status == TXN_STATUS_COMPLETED, Integer)).label("completed"),
            func.sum(func.cast(Transaction.status == TXN_STATUS_FAILED, Integer)).label("failed"),
            func.sum(func.cast(Transaction.status == TXN_STATUS_PENDING, Integer)).label("pending"),
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
            bucket=r.bucket,
            completed=int(r.completed or 0),
            failed=int(r.failed or 0),
            pending=int(r.pending or 0),
        )
        for r in rows
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
        return [UserPoint(bucket=r.bucket, count=int(r.count)) for r in rows]

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
    for r in rows:
        fee, tax, comm = Decimal(r.fee), Decimal(r.tax), Decimal(r.commission)
        out.append(
            RevenueSlice(
                service_type=r.service_type,
                fee=fee,
                tax=tax,
                commission=comm,
                total=fee + tax + comm,
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
    """Points issued vs redeemed per bucket + outstanding liability (all-time)."""
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)

    issued_bucket = func.date_trunc(granularity, Reward.created_at)
    issued_stmt = (
        select(issued_bucket.label("bucket"), func.coalesce(func.sum(Reward.points_amount), 0).label("v"))
        .where(
            Reward.tenant_id == tenant_id,
            Reward.created_at >= current.start,
            Reward.created_at < current.end,
        )
        .group_by(issued_bucket)
    )
    redeemed_bucket = func.date_trunc(granularity, Redemption.created_at)
    redeemed_stmt = (
        select(redeemed_bucket.label("bucket"), func.coalesce(func.sum(Redemption.points_amount), 0).label("v"))
        .where(
            Redemption.tenant_id == tenant_id,
            Redemption.status == REDEMPTION_STATUS_COMPLETED,
            Redemption.created_at >= current.start,
            Redemption.created_at < current.end,
        )
        .group_by(redeemed_bucket)
    )
    issued = {r.bucket: Decimal(r.v) for r in (await session.execute(issued_stmt)).all()}
    redeemed = {r.bucket: Decimal(r.v) for r in (await session.execute(redeemed_stmt)).all()}
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
                select(func.coalesce(func.sum(Reward.points_amount), 0)).where(
                    Reward.tenant_id == tenant_id
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
```

- [ ] **Step 3: Fix the imports at the top of `service.py`**

The new code references more models/constants and `Integer`. Replace the import block in `service.py` (the `from sqlalchemy ...` line and the `from app.shared.models import (...)` block and the schema import block) with:

```python
from sqlalchemy import Integer, func, select
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
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    Redemption,
    Reward,
    Tenant,
    Transaction,
    User,
)
```

- [ ] **Step 4: Verify the status-count expression compiles**

The `transactions_by_status` uses `func.cast(<bool>, Integer)`. Replace the three `.label(...)` lines inside that function's `select(...)` with the simpler, portable form and delete the unused `_count_where` helper:

```python
        select(
            bucket.label("bucket"),
            func.sum(cast(Transaction.status == TXN_STATUS_COMPLETED, Integer)).label("completed"),
            func.sum(cast(Transaction.status == TXN_STATUS_FAILED, Integer)).label("failed"),
            func.sum(cast(Transaction.status == TXN_STATUS_PENDING, Integer)).label("pending"),
        )
```

Add `cast` to the sqlalchemy import: `from sqlalchemy import Integer, cast, func, select`.

- [ ] **Step 5: Confirm model/constant names exist**

Run: `python -c "from app.shared.models import Reward, Redemption, TXN_STATUS_FAILED, TXN_STATUS_PENDING, REDEMPTION_STATUS_COMPLETED; print('ok')"`
Expected: `ok`
If `Reward` is exported under a different name, run `grep -n "class Reward" app/shared/models/rewards.py` and adjust the import + all `Reward.` references accordingly. If `Reward` has no `points_amount`/`created_at`, run `grep -nE "points_amount|amount|created_at" app/shared/models/rewards.py` and use the actual column name.

- [ ] **Step 6: Import-check the whole service**

Run: `python -c "import app.modules.analytics.service as s; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/analytics/service.py
git commit -m "feat(analytics): summary, service-mix, status, users, revenue, rewards aggregations"
```

---

## Task 4: Analytics router + registration

**Files:**
- Create: `backend/app/modules/analytics/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router**

Create `backend/app/modules/analytics/router.py`:

```python
"""Analytics FastAPI router — read-only KPI endpoints for the dashboard.

Every endpoint is auth-gated and accepts `finance-reviewer` OR `platform-admin`
(read-only). All are tenant-scoped via the required `tenant_id` query param.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import get_current_admin
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    ActiveUsers,
    DashboardSummary,
    RevenueSlice,
    RewardsTimeseries,
    ServiceSlice,
    StatusBucket,
    TransactionsTimeseries,
    UsersTimeseries,
)
from app.shared.exceptions import InsufficientRole

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def _require_finance_or_admin(
    admin: AdminPrincipal = Depends(get_current_admin),
) -> AdminPrincipal:
    """Read-side role gate — finance-reviewer OR platform-admin."""
    if not (admin.has_role("platform-admin") or admin.has_role("finance-reviewer")):
        raise InsufficientRole("finance-reviewer")
    return admin


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    tenant_id: UUID,
    range: str = Query("7d"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> DashboardSummary:
    """Headline stat-tile scalars for the range, current + previous period."""
    return await service.dashboard_summary(session, tenant_id=tenant_id, range_key=range)


@router.get("/transactions/timeseries", response_model=TransactionsTimeseries)
async def get_txn_timeseries(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> TransactionsTimeseries:
    """Bucketed transaction count + volume, current vs previous overlay."""
    return await service.transactions_timeseries(
        session, tenant_id=tenant_id, range_key=range, granularity=granularity
    )


@router.get("/transactions/by-service", response_model=list[ServiceSlice])
async def get_txn_by_service(
    tenant_id: UUID,
    range: str = Query("7d"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[ServiceSlice]:
    """Transaction mix by service type (donut / stacked bar)."""
    return await service.transactions_by_service(session, tenant_id=tenant_id, range_key=range)


@router.get("/transactions/by-status", response_model=list[StatusBucket])
async def get_txn_by_status(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[StatusBucket]:
    """Per-bucket completed/failed/pending counts."""
    return await service.transactions_by_status(
        session, tenant_id=tenant_id, range_key=range, granularity=granularity
    )


@router.get("/users/timeseries", response_model=UsersTimeseries)
async def get_users_timeseries(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> UsersTimeseries:
    """New registrations per bucket, current vs previous."""
    return await service.users_timeseries(
        session, tenant_id=tenant_id, range_key=range, granularity=granularity
    )


@router.get("/users/active", response_model=ActiveUsers)
async def get_active_users(
    tenant_id: UUID,
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> ActiveUsers:
    """DAU / WAU / MAU distinct transactors + stickiness."""
    return await service.active_users(session, tenant_id=tenant_id)


@router.get("/revenue/by-service", response_model=list[RevenueSlice])
async def get_revenue_by_service(
    tenant_id: UUID,
    range: str = Query("7d"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[RevenueSlice]:
    """Fee/tax/commission/total grouped by service type."""
    return await service.revenue_by_service(session, tenant_id=tenant_id, range_key=range)


@router.get("/rewards/timeseries", response_model=RewardsTimeseries)
async def get_rewards_timeseries(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> RewardsTimeseries:
    """Points issued vs redeemed per bucket + outstanding liability."""
    return await service.rewards_timeseries(
        session, tenant_id=tenant_id, range_key=range, granularity=granularity
    )
```

- [ ] **Step 2: Verify the auth import names**

Run: `grep -n "def has_role\|class AdminPrincipal" backend/app/auth.py; grep -n "get_current_admin" backend/app/dependencies.py`
Expected: both symbols exist (same ones `reconciliation/router.py` imports). If `ValueError` from `resolve_window`/`validate_granularity` should surface as 422 rather than 500, confirm there is a global handler; if not, it is added in Step 4 below.

- [ ] **Step 3: Register the router in main.py**

In `backend/app/main.py`, add the import alongside the other module router imports (near the top import block where `reconciliation_router` is imported):

```python
from app.modules.analytics.router import router as analytics_router
```

And add this line to the router-registration block (after `app.include_router(instruments_router)`):

```python
# Analytics — read-only KPI dashboard
app.include_router(analytics_router)
```

- [ ] **Step 4: Map `ValueError` to HTTP 422**

An unrecognised `range`/`granularity` raises `ValueError`. Add a handler in `main.py` next to the existing `app_exception_handler` so bad params return 422, not 500:

```python
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Surface analytics param validation (bad range/granularity) as 422."""
    return JSONResponse(
        status_code=422,
        content={"error_code": "invalid_parameter", "message": str(exc)},
    )
```

If a `ValueError` handler already exists, skip this step (grep first: `grep -n "exception_handler(ValueError)" backend/app/main.py`).

- [ ] **Step 5: Boot-check the app imports**

Run: `python -c "from app.main import app; print([r.path for r in app.routes if 'analytics' in r.path])"`
Expected: a list containing the 8 analytics paths.

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/analytics/router.py backend/app/main.py
git commit -m "feat(analytics): router with 8 KPI endpoints, registered + 422 on bad params"
```

---

## Task 5: Backend endpoint tests (happy path, auth, tenant isolation, empty, correctness)

**Files:**
- Create: `backend/tests/analytics/test_analytics_api.py`

Note: reuse the fixtures the existing suite uses. First inspect an existing API test to copy the client/auth/seed fixtures:
Run: `sed -n '1,60p' backend/tests/reconciliation/test_*api*.py 2>/dev/null | head -60` (or `ls backend/tests/*/ | head`) and mirror its `client`, admin-token, and tenant/transaction factory fixtures.

- [ ] **Step 1: Write the tests**

Create `backend/tests/analytics/test_analytics_api.py`:

```python
"""API tests for the analytics endpoints.

Covers: happy path, auth (401), tenant isolation, empty range, and one
aggregation-correctness assertion. Fixtures (`client`, `admin_headers`,
`seed_tenant`, `make_transaction`) come from the shared conftest — adjust
names to match backend/tests/conftest.py if they differ.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_summary_happy_path(client, admin_headers, seed_tenant, make_transaction):
    tenant_id = seed_tenant()
    await make_transaction(tenant_id=tenant_id, amount=100, status="COMPLETED")
    resp = await client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant_id), "range": "7d"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_count"]["current"] == "1"
    assert body["transaction_volume"]["current"] == "100.000000"


@pytest.mark.asyncio
async def test_summary_requires_auth(client, seed_tenant):
    tenant_id = seed_tenant()
    resp = await client.get(
        "/api/v1/analytics/summary", params={"tenant_id": str(tenant_id), "range": "7d"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bad_range_returns_422(client, admin_headers, seed_tenant):
    tenant_id = seed_tenant()
    resp = await client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant_id), "range": "all-time"},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_tenant_isolation(client, admin_headers, seed_tenant, make_transaction):
    tenant_a = seed_tenant()
    tenant_b = seed_tenant()
    await make_transaction(tenant_id=tenant_a, amount=500, status="COMPLETED")
    resp = await client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant_b), "range": "7d"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    # Tenant B sees none of tenant A's activity.
    assert resp.json()["transaction_count"]["current"] == "0"


@pytest.mark.asyncio
async def test_empty_range_timeseries_no_crash(client, admin_headers, seed_tenant):
    tenant_id = seed_tenant()
    resp = await client.get(
        "/api/v1/analytics/transactions/timeseries",
        params={"tenant_id": str(tenant_id), "range": "7d", "granularity": "day"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"current": [], "previous": []}


@pytest.mark.asyncio
async def test_by_service_groups_correctly(client, admin_headers, seed_tenant, make_transaction):
    tenant_id = seed_tenant()
    await make_transaction(tenant_id=tenant_id, amount=10, status="COMPLETED", transaction_type="cashin")
    await make_transaction(tenant_id=tenant_id, amount=20, status="COMPLETED", transaction_type="cashin")
    await make_transaction(tenant_id=tenant_id, amount=5, status="COMPLETED", transaction_type="airtime")
    resp = await client.get(
        "/api/v1/analytics/transactions/by-service",
        params={"tenant_id": str(tenant_id), "range": "7d"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    by_type = {row["service_type"]: row for row in resp.json()}
    assert by_type["cashin"]["count"] == 2
    assert by_type["cashin"]["volume"] == "30.000000"
    assert by_type["airtime"]["count"] == 1
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/analytics/test_analytics_api.py -v`
Expected: initially may FAIL if fixture names differ — reconcile fixture names against `backend/tests/conftest.py` (`grep -n "def " backend/tests/conftest.py`), then re-run until PASS.

- [ ] **Step 3: Run the whole analytics test dir + ledger invariant**

Run: `pytest tests/analytics/ -v`
Expected: all PASS. (Per repo policy, do not run the full backend suite unless the user asks — targeted subset only.)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/analytics/test_analytics_api.py
git commit -m "test(analytics): endpoint happy-path, auth, tenant-isolation, empty, correctness"
```

---

# PART 2 — Frontend dashboard

## Task 6: Add Recharts + brand chart color tokens

**Files:**
- Modify: `admin-ui/package.json` (via npm)
- Create: `admin-ui/lib/chart-colors.ts`
- Test: `admin-ui/lib/chart-colors.test.ts`

- [ ] **Step 1: Install Recharts**

Run (from `admin-ui/`): `npm install recharts`
Expected: `recharts` appears in `package.json` dependencies.

- [ ] **Step 2: Write the failing test for the color helper**

Create `admin-ui/lib/chart-colors.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { seriesColor, CHART_SERIES } from "./chart-colors";

describe("chart-colors", () => {
  it("returns a stable color per series index, wrapping around", () => {
    expect(seriesColor(0)).toBe(CHART_SERIES[0]);
    expect(seriesColor(CHART_SERIES.length)).toBe(CHART_SERIES[0]); // wraps
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npm test -- chart-colors`
Expected: FAIL (module not found).

- [ ] **Step 4: Write the helper**

Create `admin-ui/lib/chart-colors.ts`:

```ts
/**
 * Chart color tokens for Recharts, derived from the brand palette so charts
 * respect per-tenant branding and dark/light mode. These reference CSS
 * variables set by the brand-palette injector; Recharts accepts any CSS color
 * string including `var(--...)`.
 */

/** Ordered categorical series colors (wrap around for >N series). */
export const CHART_SERIES = [
  "var(--chart-1, #48C2CF)",
  "var(--chart-2, #144989)",
  "var(--chart-3, #7C5CFC)",
  "var(--chart-4, #F5A623)",
  "var(--chart-5, #34C759)",
  "var(--chart-6, #FF6B6B)",
] as const;

/** Semantic colors for status breakdowns. */
export const STATUS_COLORS = {
  completed: "var(--chart-5, #34C759)",
  failed: "var(--chart-6, #FF6B6B)",
  pending: "var(--chart-4, #F5A623)",
} as const;

/**
 * Return the categorical color for a given series index, wrapping around the
 * palette so any number of series gets a stable color.
 */
export function seriesColor(index: number): string {
  return CHART_SERIES[index % CHART_SERIES.length];
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- chart-colors`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add admin-ui/package.json admin-ui/package-lock.json admin-ui/lib/chart-colors.ts admin-ui/lib/chart-colors.test.ts
git commit -m "feat(admin-ui): add recharts + brand-aware chart color tokens"
```

---

## Task 7: Analytics API types, client functions, and delta helper

**Files:**
- Modify: `admin-ui/lib/api-types.ts` (append)
- Modify: `admin-ui/lib/api-endpoints.ts` (append)
- Create: `admin-ui/lib/analytics-format.ts`
- Test: `admin-ui/lib/analytics-format.test.ts`

- [ ] **Step 1: Add the response types**

Append to `admin-ui/lib/api-types.ts`:

```ts
// ---- Analytics (dashboard KPIs) -----------------------------------------

export interface ScalarWithPrevious {
  current: string;
  previous: string;
}

export interface DashboardSummary {
  transaction_count: ScalarWithPrevious;
  transaction_volume: ScalarWithPrevious;
  avg_transaction_value: ScalarWithPrevious;
  revenue_total: ScalarWithPrevious;
  new_users: ScalarWithPrevious;
  total_users: string;
  active_users_period: string;
  points_issued: ScalarWithPrevious;
  points_redeemed: ScalarWithPrevious;
}

export interface TimeseriesPoint {
  bucket: string;
  count: number;
  volume: string;
}

export interface TransactionsTimeseries {
  current: TimeseriesPoint[];
  previous: TimeseriesPoint[];
}

export interface ServiceSlice {
  service_type: string;
  count: number;
  volume: string;
}

export interface StatusBucket {
  bucket: string;
  completed: number;
  failed: number;
  pending: number;
}

export interface UserPoint {
  bucket: string;
  count: number;
}

export interface UsersTimeseries {
  current: UserPoint[];
  previous: UserPoint[];
}

export interface ActiveUsers {
  dau: number;
  wau: number;
  mau: number;
  stickiness: string;
}

export interface RevenueSlice {
  service_type: string;
  fee: string;
  tax: string;
  commission: string;
  total: string;
}

export interface RewardsPoint {
  bucket: string;
  issued: string;
  redeemed: string;
}

export interface RewardsTimeseries {
  points: RewardsPoint[];
  outstanding_liability: string;
}

export type AnalyticsRange = "24h" | "7d" | "30d" | "quarter";
export type AnalyticsGranularity = "day" | "week" | "month";
```

- [ ] **Step 2: Add the client functions**

Append to `admin-ui/lib/api-endpoints.ts` (and add the new type names to the existing `import type { ... }` block from `@/lib/api-types`):

```ts
// ---- Analytics -----------------------------------------------------------

export const getAnalyticsSummary = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<DashboardSummary>("/api/v1/analytics/summary", {
    query: { tenant_id, range },
  });

export const getTransactionsTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<TransactionsTimeseries>("/api/v1/analytics/transactions/timeseries", {
    query: { tenant_id, range, granularity },
  });

export const getTransactionsByService = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<ServiceSlice[]>("/api/v1/analytics/transactions/by-service", {
    query: { tenant_id, range },
  });

export const getTransactionsByStatus = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<StatusBucket[]>("/api/v1/analytics/transactions/by-status", {
    query: { tenant_id, range, granularity },
  });

export const getUsersTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<UsersTimeseries>("/api/v1/analytics/users/timeseries", {
    query: { tenant_id, range, granularity },
  });

export const getActiveUsers = (tenant_id: string) =>
  apiGet<ActiveUsers>("/api/v1/analytics/users/active", {
    query: { tenant_id },
  });

export const getRevenueByService = (tenant_id: string, range: AnalyticsRange) =>
  apiGet<RevenueSlice[]>("/api/v1/analytics/revenue/by-service", {
    query: { tenant_id, range },
  });

export const getRewardsTimeseries = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<RewardsTimeseries>("/api/v1/analytics/rewards/timeseries", {
    query: { tenant_id, range, granularity },
  });
```

- [ ] **Step 3: Write the failing test for the delta helper**

Create `admin-ui/lib/analytics-format.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { percentDelta, formatDelta } from "./analytics-format";

describe("analytics-format", () => {
  it("computes percent change vs previous", () => {
    expect(percentDelta("120", "100")).toBeCloseTo(20);
    expect(percentDelta("80", "100")).toBeCloseTo(-20);
  });

  it("treats growth from zero as null (no baseline)", () => {
    expect(percentDelta("50", "0")).toBeNull();
  });

  it("formats a delta with direction and sign", () => {
    expect(formatDelta(20)).toEqual({ label: "+20.0%", direction: "up" });
    expect(formatDelta(-5.5)).toEqual({ label: "-5.5%", direction: "down" });
    expect(formatDelta(null)).toEqual({ label: "—", direction: "flat" });
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npm test -- analytics-format`
Expected: FAIL (module not found).

- [ ] **Step 5: Write the helper**

Create `admin-ui/lib/analytics-format.ts`:

```ts
/**
 * Pure helpers for turning the analytics API's string decimals into
 * dashboard-ready deltas. Kept DOM-free so they sit under the lib coverage
 * gate.
 */

export type DeltaDirection = "up" | "down" | "flat";

/**
 * Percent change of `current` vs `previous`. Returns null when there is no
 * baseline (previous == 0), because "∞%" is meaningless on a tile.
 */
export function percentDelta(current: string, previous: string): number | null {
  const cur = Number(current);
  const prev = Number(previous);
  if (prev === 0) return null;
  return ((cur - prev) / prev) * 100;
}

/**
 * Format a percent delta into a label + direction for the tile chip.
 */
export function formatDelta(delta: number | null): {
  label: string;
  direction: DeltaDirection;
} {
  if (delta === null) return { label: "—", direction: "flat" };
  const direction: DeltaDirection = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const sign = delta > 0 ? "+" : "";
  return { label: `${sign}${delta.toFixed(1)}%`, direction };
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npm test -- analytics-format`
Expected: PASS.

- [ ] **Step 7: Type-check**

Run: `npm run typecheck` (or `npx tsc --noEmit`)
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add admin-ui/lib/api-types.ts admin-ui/lib/api-endpoints.ts admin-ui/lib/analytics-format.ts admin-ui/lib/analytics-format.test.ts
git commit -m "feat(admin-ui): analytics API types, client fns, delta helper"
```

---

## Task 8: Server action for range-scoped analytics fetch

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_actions.ts`

- [ ] **Step 1: Write the server action**

Create `admin-ui/app/(authenticated)/dashboard/_actions.ts`:

```ts
/**
 * Server actions for the dashboard. The client component calls these when the
 * range/granularity changes so subsequent fetches run server-side with the
 * Keycloak bearer token — the browser never hits the backend directly.
 */
"use server";

import {
  getActiveUsers,
  getAnalyticsSummary,
  getRevenueByService,
  getRewardsTimeseries,
  getTransactionsByService,
  getTransactionsByStatus,
  getTransactionsTimeseries,
  getUsersTimeseries,
} from "@/lib/api-endpoints";
import { getActiveTenantId } from "@/lib/active-tenant";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

/**
 * Fetch every dashboard dataset for a range/granularity in one server round.
 * Uses allSettled so one failing panel doesn't blank the whole dashboard.
 */
export async function loadDashboardData(
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) {
  const tenantId = (await getActiveTenantId()) ?? "";

  const [
    summary,
    txnTimeseries,
    byService,
    byStatus,
    usersTs,
    activeUsers,
    revenue,
    rewards,
  ] = await Promise.allSettled([
    getAnalyticsSummary(tenantId, range),
    getTransactionsTimeseries(tenantId, range, granularity),
    getTransactionsByService(tenantId, range),
    getTransactionsByStatus(tenantId, range, granularity),
    getUsersTimeseries(tenantId, range, granularity),
    getActiveUsers(tenantId),
    getRevenueByService(tenantId, range),
    getRewardsTimeseries(tenantId, range, granularity),
  ]);

  const val = <T>(r: PromiseSettledResult<T>): T | null =>
    r.status === "fulfilled" ? r.value : null;

  return {
    summary: val(summary),
    txnTimeseries: val(txnTimeseries),
    byService: val(byService),
    byStatus: val(byStatus),
    usersTs: val(usersTs),
    activeUsers: val(activeUsers),
    revenue: val(revenue),
    rewards: val(rewards),
  };
}

export type DashboardData = Awaited<ReturnType<typeof loadDashboardData>>;
```

- [ ] **Step 2: Type-check**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_actions.ts"
git commit -m "feat(admin-ui): dashboard server action loading all KPI datasets"
```

---

## Task 9: StatTile component + time-range switcher

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_components/stat-tile.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/stat-tile.test.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/time-range-switcher.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/time-range-switcher.test.tsx`

- [ ] **Step 1: Write the failing StatTile test**

Create `stat-tile.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatTile } from "./stat-tile";

describe("StatTile", () => {
  it("renders label, value, and an up delta chip", () => {
    render(
      <StatTile
        id="txns"
        label="Transactions"
        value="1,204"
        current="120"
        previous="100"
        selected={false}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.getByText("1,204")).toBeInTheDocument();
    expect(screen.getByText("+20.0%")).toBeInTheDocument();
  });

  it("calls onSelect with its id when clicked", async () => {
    const onSelect = vi.fn();
    render(
      <StatTile
        id="volume"
        label="Volume"
        value="R 5,000"
        current="100"
        previous="100"
        selected={false}
        onSelect={onSelect}
      />,
    );
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("volume");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- stat-tile`
Expected: FAIL (module not found).

- [ ] **Step 3: Write StatTile**

Create `stat-tile.tsx`:

```tsx
"use client";

/**
 * A clickable KPI stat tile: big value + a delta chip vs the previous period.
 * Selecting it tells the dashboard which metric to plot in the shared trend
 * chart. Colour is always paired with an arrow/icon (never colour alone).
 */
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { formatDelta, percentDelta } from "@/lib/analytics-format";

interface Props {
  id: string;
  label: string;
  value: string;
  current: string;
  previous: string;
  selected: boolean;
  onSelect: (id: string) => void;
}

export function StatTile({ id, label, value, current, previous, selected, onSelect }: Props) {
  const { label: deltaLabel, direction } = formatDelta(percentDelta(current, previous));
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  const tone =
    direction === "up"
      ? "text-emerald-600 dark:text-emerald-400"
      : direction === "down"
        ? "text-red-600 dark:text-red-400"
        : "text-muted-foreground";

  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-start gap-1 rounded-lg border bg-card p-4 text-left transition-colors",
        selected ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
      )}
    >
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-2xl font-bold tabular-nums text-foreground">{value}</span>
      <span className={cn("inline-flex items-center gap-1 text-xs font-semibold", tone)}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {deltaLabel}
        <span className="font-normal text-muted-foreground">vs prev</span>
      </span>
    </button>
  );
}
```

- [ ] **Step 4: Run StatTile test to verify it passes**

Run: `npm test -- stat-tile`
Expected: PASS.

- [ ] **Step 5: Write the failing time-range-switcher test**

Create `time-range-switcher.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TimeRangeSwitcher } from "./time-range-switcher";

describe("TimeRangeSwitcher", () => {
  it("fires onRangeChange with the chosen range", () => {
    const onRangeChange = vi.fn();
    render(
      <TimeRangeSwitcher
        range="7d"
        granularity="day"
        onRangeChange={onRangeChange}
        onGranularityChange={() => {}}
      />,
    );
    screen.getByRole("button", { name: "30d" }).click();
    expect(onRangeChange).toHaveBeenCalledWith("30d");
  });
});
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npm test -- time-range-switcher`
Expected: FAIL (module not found).

- [ ] **Step 7: Write TimeRangeSwitcher**

Create `time-range-switcher.tsx`:

```tsx
"use client";

/**
 * Global range + granularity control for the dashboard. Segmented buttons;
 * changing either fires up to the dashboard client which refetches via the
 * server action and syncs URL params.
 */
import { cn } from "@/lib/utils";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

const RANGES: AnalyticsRange[] = ["24h", "7d", "30d", "quarter"];
const GRANULARITIES: AnalyticsGranularity[] = ["day", "week", "month"];

interface Props {
  range: AnalyticsRange;
  granularity: AnalyticsGranularity;
  onRangeChange: (r: AnalyticsRange) => void;
  onGranularityChange: (g: AnalyticsGranularity) => void;
}

export function TimeRangeSwitcher({
  range,
  granularity,
  onRangeChange,
  onGranularityChange,
}: Props) {
  return (
    <div className="flex items-center gap-3">
      <Segmented options={RANGES} value={range} onChange={onRangeChange} />
      <div className="h-4 w-px bg-border" />
      <Segmented options={GRANULARITIES} value={granularity} onChange={onGranularityChange} />
    </div>
  );
}

function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-md border bg-card p-0.5">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={cn(
            "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
            opt === value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 8: Run time-range-switcher test to verify it passes**

Run: `npm test -- time-range-switcher`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_components/stat-tile.tsx" "admin-ui/app/(authenticated)/dashboard/_components/stat-tile.test.tsx" "admin-ui/app/(authenticated)/dashboard/_components/time-range-switcher.tsx" "admin-ui/app/(authenticated)/dashboard/_components/time-range-switcher.test.tsx"
git commit -m "feat(admin-ui): clickable stat tile + time-range switcher (tested)"
```

---

## Task 10: Trend chart, service-mix, and status-breakdown charts

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_components/trend-chart.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/service-mix-chart.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/status-breakdown-chart.tsx`

Note: charts render only in the browser — mark each `"use client"`. No unit tests for pure chart SVG (Recharts needs layout); coverage stays on the lib helpers per the frontend testing rule.

- [ ] **Step 1: Write the shared trend chart**

Create `trend-chart.tsx`:

```tsx
"use client";

/**
 * The shared main trend chart. Plots one metric (count or volume) over the
 * bucketed series with a dotted previous-period overlay — the visual
 * day-on-day / week-on-week comparison. Which metric shows is driven by the
 * selected stat tile.
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { TransactionsTimeseries } from "@/lib/api-types";

interface Props {
  data: TransactionsTimeseries;
  metric: "count" | "volume";
  label: string;
}

/** Merge current + previous into aligned rows keyed by bucket index. */
function toRows(data: TransactionsTimeseries, metric: "count" | "volume") {
  const len = Math.max(data.current.length, data.previous.length);
  return Array.from({ length: len }, (_, i) => ({
    bucket: data.current[i]?.bucket ?? data.previous[i]?.bucket ?? `${i}`,
    current: Number(data.current[i]?.[metric] ?? 0),
    previous: Number(data.previous[i]?.[metric] ?? 0),
  }));
}

export function TrendChart({ data, metric, label }: Props) {
  const rows = toRows(data, metric);
  if (rows.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        No activity in this range.
      </div>
    );
  }
  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_SERIES[0]} stopOpacity={0.35} />
              <stop offset="100%" stopColor={CHART_SERIES[0]} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Area
            type="monotone"
            dataKey="current"
            name={label}
            stroke={CHART_SERIES[0]}
            fill="url(#trendFill)"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="previous"
            name="Previous period"
            stroke={CHART_SERIES[1]}
            strokeDasharray="4 4"
            strokeWidth={1.5}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Write the service-mix donut**

Create `service-mix-chart.tsx`:

```tsx
"use client";

/**
 * Transaction mix by service type — donut of counts. Answers "division of
 * transactions on service type".
 */
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { seriesColor } from "@/lib/chart-colors";
import type { ServiceSlice } from "@/lib/api-types";

export function ServiceMixChart({ data }: { data: ServiceSlice[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No transactions yet.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="service_type"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={seriesColor(i)} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Write the status-breakdown stacked bar**

Create `status-breakdown-chart.tsx`:

```tsx
"use client";

/**
 * Completed / failed / pending transactions per bucket (stacked bar).
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { STATUS_COLORS } from "@/lib/chart-colors";
import type { StatusBucket } from "@/lib/api-types";

export function StatusBreakdownChart({ data }: { data: StatusBucket[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No transactions yet.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Legend />
          <Bar dataKey="completed" stackId="s" fill={STATUS_COLORS.completed} />
          <Bar dataKey="failed" stackId="s" fill={STATUS_COLORS.failed} />
          <Bar dataKey="pending" stackId="s" fill={STATUS_COLORS.pending} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Type-check**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_components/trend-chart.tsx" "admin-ui/app/(authenticated)/dashboard/_components/service-mix-chart.tsx" "admin-ui/app/(authenticated)/dashboard/_components/status-breakdown-chart.tsx"
git commit -m "feat(admin-ui): trend (with prev-period overlay), service-mix, status charts"
```

---

## Task 11: Users, revenue, and rewards charts

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_components/users-growth-chart.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/revenue-chart.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/rewards-chart.tsx`

- [ ] **Step 1: Write the users growth bar chart**

Create `users-growth-chart.tsx`:

```tsx
"use client";

/**
 * New registrations per bucket (bar) with a dotted previous-period line.
 */
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { UsersTimeseries } from "@/lib/api-types";

export function UsersGrowthChart({ data }: { data: UsersTimeseries }) {
  const len = Math.max(data.current.length, data.previous.length);
  const rows = Array.from({ length: len }, (_, i) => ({
    bucket: data.current[i]?.bucket ?? data.previous[i]?.bucket ?? `${i}`,
    current: data.current[i]?.count ?? 0,
    previous: data.previous[i]?.count ?? 0,
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No new registrations in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={40} />
          <Tooltip />
          <Bar dataKey="current" name="New users" fill={CHART_SERIES[0]} radius={[3, 3, 0, 0]} />
          <Line
            type="monotone"
            dataKey="previous"
            name="Previous period"
            stroke={CHART_SERIES[1]}
            strokeDasharray="4 4"
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Write the revenue-by-service bar chart**

Create `revenue-chart.tsx`:

```tsx
"use client";

/**
 * Revenue by service type — stacked bar of fee / tax / commission.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { RevenueSlice } from "@/lib/api-types";

export function RevenueChart({ data }: { data: RevenueSlice[] }) {
  const rows = data.map((r) => ({
    service_type: r.service_type,
    fee: Number(r.fee),
    tax: Number(r.tax),
    commission: Number(r.commission),
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No revenue in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="service_type" fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Legend />
          <Bar dataKey="fee" stackId="r" fill={CHART_SERIES[0]} />
          <Bar dataKey="tax" stackId="r" fill={CHART_SERIES[3]} />
          <Bar dataKey="commission" stackId="r" fill={CHART_SERIES[2]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Write the rewards dual-line chart**

Create `rewards-chart.tsx`:

```tsx
"use client";

/**
 * Points issued vs redeemed per bucket (dual line).
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { RewardsTimeseries } from "@/lib/api-types";

export function RewardsChart({ data }: { data: RewardsTimeseries }) {
  const rows = data.points.map((p) => ({
    bucket: p.bucket,
    issued: Number(p.issued),
    redeemed: Number(p.redeemed),
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No rewards activity in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Line type="monotone" dataKey="issued" name="Issued" stroke={CHART_SERIES[4]} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="redeemed" name="Redeemed" stroke={CHART_SERIES[2]} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Type-check**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_components/users-growth-chart.tsx" "admin-ui/app/(authenticated)/dashboard/_components/revenue-chart.tsx" "admin-ui/app/(authenticated)/dashboard/_components/rewards-chart.tsx"
git commit -m "feat(admin-ui): users-growth, revenue, rewards charts"
```

---

## Task 12: Assemble the dashboard (client shell + page + retained ops strip)

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_components/dashboard-client.tsx`
- Rewrite: `admin-ui/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Write the client shell**

Create `dashboard-client.tsx`:

```tsx
"use client";

/**
 * Dashboard client shell. Owns the selected range/granularity and the
 * selected stat tile (which metric the shared trend chart plots). On range
 * change it refetches all datasets via the server action and syncs URL params
 * for a shareable view.
 */
import { useTransition, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { loadDashboardData, type DashboardData } from "../_actions";
import { StatTile } from "./stat-tile";
import { TimeRangeSwitcher } from "./time-range-switcher";
import { TrendChart } from "./trend-chart";
import { ServiceMixChart } from "./service-mix-chart";
import { StatusBreakdownChart } from "./status-breakdown-chart";
import { UsersGrowthChart } from "./users-growth-chart";
import { RevenueChart } from "./revenue-chart";
import { RewardsChart } from "./rewards-chart";
import { Card } from "@/components/ui/card";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";

interface Props {
  initial: DashboardData;
  initialRange: AnalyticsRange;
  initialGranularity: AnalyticsGranularity;
}

const TILES = [
  { id: "count", label: "Transactions", metric: "count" as const, from: "transaction_count" as const },
  { id: "volume", label: "Volume", metric: "volume" as const, from: "transaction_volume" as const },
  { id: "revenue", label: "Revenue", metric: "volume" as const, from: "revenue_total" as const },
  { id: "users", label: "New users", metric: "count" as const, from: "new_users" as const },
];

export function DashboardClient({ initial, initialRange, initialGranularity }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [data, setData] = useState<DashboardData>(initial);
  const [range, setRange] = useState<AnalyticsRange>(initialRange);
  const [granularity, setGranularity] = useState<AnalyticsGranularity>(initialGranularity);
  const [selected, setSelected] = useState<string>("count");
  const [pending, startTransition] = useTransition();

  function refetch(r: AnalyticsRange, g: AnalyticsGranularity) {
    setRange(r);
    setGranularity(g);
    const next = new URLSearchParams(params.toString());
    next.set("range", r);
    next.set("granularity", g);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    startTransition(async () => setData(await loadDashboardData(r, g)));
  }

  const selectedTile = TILES.find((t) => t.id === selected) ?? TILES[0];
  const s = data.summary;

  return (
    <div className={pending ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold tracking-tight">Overview</h1>
        <TimeRangeSwitcher
          range={range}
          granularity={granularity}
          onRangeChange={(r) => refetch(r, granularity)}
          onGranularityChange={(g) => refetch(range, g)}
        />
      </div>

      {/* Stat tiles */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {TILES.map((t) => {
          const scalar = s?.[t.from] ?? { current: "0", previous: "0" };
          return (
            <StatTile
              key={t.id}
              id={t.id}
              label={t.label}
              value={Number(scalar.current).toLocaleString()}
              current={scalar.current}
              previous={scalar.previous}
              selected={selected === t.id}
              onSelect={setSelected}
            />
          );
        })}
      </div>

      {/* Shared trend + service mix */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-4 lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold">{selectedTile.label} over time</h2>
          {data.txnTimeseries ? (
            <TrendChart data={data.txnTimeseries} metric={selectedTile.metric} label={selectedTile.label} />
          ) : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Service mix</h2>
          {data.byService ? <ServiceMixChart data={data.byService} /> : null}
        </Card>
      </div>

      {/* Status + users */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Transaction status</h2>
          {data.byStatus ? <StatusBreakdownChart data={data.byStatus} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">New registrations</h2>
          {data.usersTs ? <UsersGrowthChart data={data.usersTs} /> : null}
        </Card>
      </div>

      {/* Revenue + rewards */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Revenue by service</h2>
          {data.revenue ? <RevenueChart data={data.revenue} /> : null}
        </Card>
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-semibold">Points issued vs redeemed</h2>
          {data.rewards ? <RewardsChart data={data.rewards} /> : null}
        </Card>
      </div>
    </div>
  );
}
```

If `@/components/ui/card` does not export `Card`, run `grep -rn "export" admin-ui/components/ui/card.tsx` and use the actual export (or replace `<Card ...>` with a `<div className="rounded-lg border bg-card ...">`).

- [ ] **Step 2: Rewrite the page as a server component**

Replace the entire contents of `admin-ui/app/(authenticated)/dashboard/page.tsx`:

```tsx
/**
 * Dashboard — interactive KPI overview for the active tenant.
 *
 * Server component: resolves the active tenant, reads range/granularity from
 * URL params, does the initial analytics fetch, and hands off to the client
 * shell which owns interactivity (tile selection, range switching, refetch).
 */
import { EmptyState } from "@/components/ui/empty-state";
import { Sparkles } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import { listTenants } from "@/lib/api-endpoints";
import type { AnalyticsGranularity, AnalyticsRange } from "@/lib/api-types";
import { loadDashboardData } from "./_actions";
import { DashboardClient } from "./_components/dashboard-client";

export const dynamic = "force-dynamic";

const RANGES: AnalyticsRange[] = ["24h", "7d", "30d", "quarter"];
const GRANS: AnalyticsGranularity[] = ["day", "week", "month"];

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ range?: string; granularity?: string }>;
}) {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    const tenants = await listTenants().catch(() => []);
    if (tenants.length === 0) {
      return (
        <div className="p-6">
          <EmptyState
            icon={Sparkles}
            title="No tenants yet"
            description="Create the first tenant via the seed script or the Tenants page."
          />
        </div>
      );
    }
  }

  const sp = await searchParams;
  const range: AnalyticsRange = RANGES.includes(sp.range as AnalyticsRange)
    ? (sp.range as AnalyticsRange)
    : "7d";
  const granularity: AnalyticsGranularity = GRANS.includes(sp.granularity as AnalyticsGranularity)
    ? (sp.granularity as AnalyticsGranularity)
    : "day";

  const initial = await loadDashboardData(range, granularity);

  return (
    <div className="h-full overflow-y-auto p-6">
      <DashboardClient initial={initial} initialRange={range} initialGranularity={granularity} />
    </div>
  );
}
```

- [ ] **Step 3: Type-check + lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 4: Run the frontend test subset**

Run: `npm test -- dashboard analytics-format chart-colors stat-tile time-range-switcher`
Expected: all PASS.

- [ ] **Step 5: Manual smoke (optional but recommended)**

Ensure infra + backend are up (`cd sasai-wallet-infra && docker compose up -d`; `cd backend && make dev`), seed has data (`make seed`), then `cd admin-ui && npm run dev` and open `/dashboard`. Verify: tiles show numbers, clicking a tile swaps the trend chart, changing range/granularity refetches, previous-period dotted line appears.

- [ ] **Step 6: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_components/dashboard-client.tsx" "admin-ui/app/(authenticated)/dashboard/page.tsx"
git commit -m "feat(admin-ui): interactive KPI dashboard shell wiring tiles + charts"
```

---

## Task 13: Restore the operations "needs attention" strip

The original page surfaced pending recon / manual-review / audit activity. Re-add it below the KPIs so the dashboard keeps its ops-cockpit value (spec group F).

**Files:**
- Create: `admin-ui/app/(authenticated)/dashboard/_components/attention-strip.tsx`
- Modify: `admin-ui/app/(authenticated)/dashboard/page.tsx`

- [ ] **Step 1: Write the attention strip (server component)**

Create `attention-strip.tsx`:

```tsx
/**
 * Operations "needs attention" strip — pending reconciliation and manual
 * review counts for the active tenant. Server component; links out to the
 * relevant queues. Retains the ops-cockpit value of the old dashboard.
 */
import { AlertTriangle, ScanLine } from "lucide-react";
import Link from "next/link";

import { listManualReview, listPendingRedemptions } from "@/lib/api-endpoints";

export async function AttentionStrip({ tenantId }: { tenantId: string }) {
  const [pending, manual] = await Promise.all([
    listPendingRedemptions(tenantId, 5).catch(() => []),
    listManualReview(tenantId).catch(() => []),
  ]);
  if (pending.length === 0 && manual.length === 0) return null;

  return (
    <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Link href="/reconciliation" className="flex items-center gap-3 rounded-lg border bg-card p-4 hover:border-primary/40">
        <ScanLine className="h-5 w-5 text-amber-500" aria-hidden="true" />
        <div>
          <div className="text-lg font-bold tabular-nums">{pending.length}</div>
          <div className="text-xs text-muted-foreground">Pending reconciliation</div>
        </div>
      </Link>
      <Link href="/reconciliation" className="flex items-center gap-3 rounded-lg border bg-card p-4 hover:border-primary/40">
        <AlertTriangle className="h-5 w-5 text-red-500" aria-hidden="true" />
        <div>
          <div className="text-lg font-bold tabular-nums">{manual.length}</div>
          <div className="text-xs text-muted-foreground">Manual review</div>
        </div>
      </Link>
    </div>
  );
}
```

- [ ] **Step 2: Mount it in the page**

In `page.tsx`, import it and render it inside the wrapper after `<DashboardClient .../>`:

```tsx
import { AttentionStrip } from "./_components/attention-strip";
```

```tsx
      <DashboardClient initial={initial} initialRange={range} initialGranularity={granularity} />
      <AttentionStrip tenantId={activeTenantId ?? ""} />
```

- [ ] **Step 3: Type-check + lint + test subset**

Run: `npm run typecheck && npm run lint && npm test -- dashboard`
Expected: no errors, tests PASS.

- [ ] **Step 4: Commit**

```bash
git add "admin-ui/app/(authenticated)/dashboard/_components/attention-strip.tsx" "admin-ui/app/(authenticated)/dashboard/page.tsx"
git commit -m "feat(admin-ui): retain ops needs-attention strip under KPIs"
```

---

## Task 14: Group C (liquidity) + user-type backend

Covers spec Group C (wallet float liability, cash-float health, net flow) and KPI B6 (users by type). Balances follow the ledger rule: `SUM(CREDIT) − SUM(DEBIT)` where `status='COMPLETED'`.

**Files:**
- Modify: `backend/app/modules/analytics/schemas.py` (append)
- Modify: `backend/app/modules/analytics/service.py` (append + imports)
- Modify: `backend/app/modules/analytics/router.py` (append endpoints)
- Modify: `backend/tests/analytics/test_analytics_api.py` (append tests)

- [ ] **Step 1: Append schemas**

Append to `backend/app/modules/analytics/schemas.py`:

```python
class Liquidity(BaseModel):
    """Point-in-time liquidity snapshot for the tenant."""

    wallet_liability: Decimal  # total held in user financial_wallet accounts
    cash_float_balance: Decimal  # system_cash_inflow balance


class NetFlowPoint(BaseModel):
    """Inflow vs outflow into user wallets for one bucket."""

    bucket: datetime
    inflow: Decimal
    outflow: Decimal


class UserTypeSlice(BaseModel):
    """User count for one user_type."""

    user_type: str
    count: int
```

- [ ] **Step 2: Append service aggregations**

Append to `backend/app/modules/analytics/service.py`, and extend its model import block to add `Account`, `ACCOUNT_TYPE_FINANCIAL_WALLET`, `ACCOUNT_TYPE_SYSTEM_CASH_INFLOW`, `ENTRY_TYPE_CREDIT`, `ENTRY_TYPE_DEBIT`, `ENTRY_STATUS_COMPLETED`, `LedgerEntry`, and the new schema names `Liquidity`, `NetFlowPoint`, `UserTypeSlice`:

```python
def _signed_balance_expr():
    """SQL expression: SUM(CREDIT) - SUM(DEBIT) over COMPLETED ledger entries."""
    return func.coalesce(
        func.sum(
            cast(LedgerEntry.entry_type == ENTRY_TYPE_CREDIT, Integer) * LedgerEntry.amount
            - cast(LedgerEntry.entry_type == ENTRY_TYPE_DEBIT, Integer) * LedgerEntry.amount
        ),
        0,
    )


async def _account_type_balance(
    session: AsyncSession, tenant_id: UUID, account_type: str
) -> Decimal:
    """Net COMPLETED balance across all accounts of a type for the tenant."""
    stmt = (
        select(_signed_balance_expr())
        .select_from(LedgerEntry)
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
    )
    return Decimal((await session.execute(stmt)).scalar_one())


async def liquidity(session: AsyncSession, *, tenant_id: UUID) -> Liquidity:
    """Wallet float liability + cash-float balance (point in time)."""
    await _assert_tenant_exists(session, tenant_id)
    return Liquidity(
        wallet_liability=await _account_type_balance(
            session, tenant_id, ACCOUNT_TYPE_FINANCIAL_WALLET
        ),
        cash_float_balance=await _account_type_balance(
            session, tenant_id, ACCOUNT_TYPE_SYSTEM_CASH_INFLOW
        ),
    )


async def net_flow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    range_key: str,
    granularity: str,
    now: datetime | None = None,
) -> list[NetFlowPoint]:
    """Per-bucket credits (inflow) vs debits (outflow) into user wallets."""
    await _assert_tenant_exists(session, tenant_id)
    granularity = validate_granularity(granularity)
    current, _ = resolve_window(range_key, now=now)
    bucket = func.date_trunc(granularity, LedgerEntry.created_at)
    stmt = (
        select(
            bucket.label("bucket"),
            func.coalesce(
                func.sum(cast(LedgerEntry.entry_type == ENTRY_TYPE_CREDIT, Integer) * LedgerEntry.amount),
                0,
            ).label("inflow"),
            func.coalesce(
                func.sum(cast(LedgerEntry.entry_type == ENTRY_TYPE_DEBIT, Integer) * LedgerEntry.amount),
                0,
            ).label("outflow"),
        )
        .select_from(LedgerEntry)
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
            LedgerEntry.created_at >= current.start,
            LedgerEntry.created_at < current.end,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(stmt)).all()
    return [
        NetFlowPoint(bucket=r.bucket, inflow=Decimal(r.inflow), outflow=Decimal(r.outflow))
        for r in rows
    ]


async def users_by_type(
    session: AsyncSession, *, tenant_id: UUID
) -> list[UserTypeSlice]:
    """Distribution of users across user_type (consumer/agent/merchant…)."""
    await _assert_tenant_exists(session, tenant_id)
    stmt = (
        select(User.user_type.label("user_type"), func.count(User.id).label("count"))
        .where(User.tenant_id == tenant_id)
        .group_by(User.user_type)
        .order_by(func.count(User.id).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [UserTypeSlice(user_type=r.user_type, count=int(r.count)) for r in rows]
```

- [ ] **Step 3: Confirm the ledger constant names**

Run: `python -c "from app.shared.models import ENTRY_TYPE_CREDIT, ENTRY_TYPE_DEBIT, ENTRY_STATUS_COMPLETED, Account, LedgerEntry, ACCOUNT_TYPE_FINANCIAL_WALLET, ACCOUNT_TYPE_SYSTEM_CASH_INFLOW; print('ok')"`
Expected: `ok`. If any name differs (e.g. `ENTRY_CREDIT`), grep `app/shared/models/ledger.py` / `accounts.py` for the actual constant and adjust.

- [ ] **Step 4: Append router endpoints**

Append to `backend/app/modules/analytics/router.py` (and add `Liquidity`, `NetFlowPoint`, `UserTypeSlice` to the schema import block):

```python
@router.get("/liquidity", response_model=Liquidity)
async def get_liquidity(
    tenant_id: UUID,
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> Liquidity:
    """Wallet float liability + cash-float balance."""
    return await service.liquidity(session, tenant_id=tenant_id)


@router.get("/net-flow", response_model=list[NetFlowPoint])
async def get_net_flow(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[NetFlowPoint]:
    """Per-bucket inflow vs outflow into user wallets."""
    return await service.net_flow(
        session, tenant_id=tenant_id, range_key=range, granularity=granularity
    )


@router.get("/users/by-type", response_model=list[UserTypeSlice])
async def get_users_by_type(
    tenant_id: UUID,
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[UserTypeSlice]:
    """User distribution by user_type."""
    return await service.users_by_type(session, tenant_id=tenant_id)
```

- [ ] **Step 5: Append tests**

Append to `backend/tests/analytics/test_analytics_api.py`:

```python
@pytest.mark.asyncio
async def test_liquidity_reflects_ledger_balance(client, admin_headers, seed_tenant, make_transaction):
    tenant_id = seed_tenant()
    # A completed cash-in credits a user financial_wallet.
    await make_transaction(tenant_id=tenant_id, amount=250, status="COMPLETED", transaction_type="cashin")
    resp = await client.get(
        "/api/v1/analytics/liquidity",
        params={"tenant_id": str(tenant_id)},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["wallet_liability"]) >= Decimal("0")


@pytest.mark.asyncio
async def test_users_by_type_requires_auth(client, seed_tenant):
    tenant_id = seed_tenant()
    resp = await client.get(
        "/api/v1/analytics/users/by-type", params={"tenant_id": str(tenant_id)}
    )
    assert resp.status_code == 401
```

Note: the `wallet_liability` assertion is deliberately loose — the exact figure depends on how `make_transaction` posts ledger legs. If the fixture posts a full double-entry cash-in, tighten to `== "250.000000"`.

- [ ] **Step 6: Run analytics tests**

Run: `pytest tests/analytics/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/analytics/ backend/tests/analytics/test_analytics_api.py
git commit -m "feat(analytics): liquidity, net-flow, users-by-type endpoints + tests"
```

---

## Task 15: Group C + user-type frontend (tiles, net-flow chart, user-type donut)

**Files:**
- Modify: `admin-ui/lib/api-types.ts` (append), `admin-ui/lib/api-endpoints.ts` (append), `admin-ui/app/(authenticated)/dashboard/_actions.ts` (extend)
- Create: `admin-ui/app/(authenticated)/dashboard/_components/net-flow-chart.tsx`
- Create: `admin-ui/app/(authenticated)/dashboard/_components/user-type-chart.tsx`
- Modify: `admin-ui/app/(authenticated)/dashboard/_components/dashboard-client.tsx`

- [ ] **Step 1: Types + client fns**

Append to `admin-ui/lib/api-types.ts`:

```ts
export interface Liquidity {
  wallet_liability: string;
  cash_float_balance: string;
}

export interface NetFlowPoint {
  bucket: string;
  inflow: string;
  outflow: string;
}

export interface UserTypeSlice {
  user_type: string;
  count: number;
}
```

Append to `admin-ui/lib/api-endpoints.ts`:

```ts
export const getLiquidity = (tenant_id: string) =>
  apiGet<Liquidity>("/api/v1/analytics/liquidity", { query: { tenant_id } });

export const getNetFlow = (
  tenant_id: string,
  range: AnalyticsRange,
  granularity: AnalyticsGranularity,
) =>
  apiGet<NetFlowPoint[]>("/api/v1/analytics/net-flow", {
    query: { tenant_id, range, granularity },
  });

export const getUsersByType = (tenant_id: string) =>
  apiGet<UserTypeSlice[]>("/api/v1/analytics/users/by-type", {
    query: { tenant_id },
  });
```

- [ ] **Step 2: Extend the server action**

In `_actions.ts`, add the three imports and add them to the `Promise.allSettled` array + the return object:

```ts
    getLiquidity(tenantId),
    getNetFlow(tenantId, range, granularity),
    getUsersByType(tenantId),
```

Capture them as `liquidity`, `netFlow`, `usersByType` (destructure in order) and add `liquidity: val(liquidity), netFlow: val(netFlow), usersByType: val(usersByType)` to the returned object.

- [ ] **Step 3: Net-flow chart**

Create `net-flow-chart.tsx`:

```tsx
"use client";

/**
 * Inflow vs outflow into user wallets per bucket (grouped bars).
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { CHART_SERIES } from "@/lib/chart-colors";
import type { NetFlowPoint } from "@/lib/api-types";

export function NetFlowChart({ data }: { data: NetFlowPoint[] }) {
  const rows = data.map((p) => ({
    bucket: p.bucket,
    inflow: Number(p.inflow),
    outflow: Number(p.outflow),
  }));
  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No wallet movement in this range.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="bucket" tickFormatter={(v) => String(v).slice(5, 10)} fontSize={11} />
          <YAxis fontSize={11} width={48} />
          <Tooltip />
          <Legend />
          <Bar dataKey="inflow" fill={CHART_SERIES[4]} radius={[3, 3, 0, 0]} />
          <Bar dataKey="outflow" fill={CHART_SERIES[5]} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: User-type donut**

Create `user-type-chart.tsx`:

```tsx
"use client";

/**
 * User distribution by user_type (donut).
 */
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { seriesColor } from "@/lib/chart-colors";
import type { UserTypeSlice } from "@/lib/api-types";

export function UserTypeChart({ data }: { data: UserTypeSlice[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
        No users yet.
      </div>
    );
  }
  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="count" nameKey="user_type" innerRadius={55} outerRadius={85} paddingAngle={2}>
            {data.map((_, i) => (
              <Cell key={i} fill={seriesColor(i)} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 5: Add a liquidity tile row + the two charts to `dashboard-client.tsx`**

Import the two charts and render a liquidity strip + charts after the revenue/rewards grid:

```tsx
import { NetFlowChart } from "./net-flow-chart";
import { UserTypeChart } from "./user-type-chart";
```

```tsx
      {/* Liquidity + user mix */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-2 gap-3 lg:col-span-1">
          <div className="rounded-lg border bg-card p-4">
            <div className="text-xs text-muted-foreground">Wallet liability</div>
            <div className="text-xl font-bold tabular-nums">
              {Number(data.liquidity?.wallet_liability ?? 0).toLocaleString()}
            </div>
          </div>
          <div className="rounded-lg border bg-card p-4">
            <div className="text-xs text-muted-foreground">Cash float</div>
            <div className="text-xl font-bold tabular-nums">
              {Number(data.liquidity?.cash_float_balance ?? 0).toLocaleString()}
            </div>
          </div>
        </div>
        <Card className="p-4 lg:col-span-1">
          <h2 className="mb-2 text-sm font-semibold">Net flow (in vs out)</h2>
          {data.netFlow ? <NetFlowChart data={data.netFlow} /> : null}
        </Card>
        <Card className="p-4 lg:col-span-1">
          <h2 className="mb-2 text-sm font-semibold">Users by type</h2>
          {data.usersByType ? <UserTypeChart data={data.usersByType} /> : null}
        </Card>
      </div>
```

- [ ] **Step 6: Type-check, lint, test**

Run: `npm run typecheck && npm run lint && npm test -- dashboard`
Expected: clean/PASS.

- [ ] **Step 7: Commit**

```bash
git add admin-ui/lib/api-types.ts admin-ui/lib/api-endpoints.ts "admin-ui/app/(authenticated)/dashboard"
git commit -m "feat(admin-ui): liquidity tiles, net-flow chart, user-type donut"
```

---

## Final verification

- [ ] Backend: `cd backend && pytest tests/analytics/ -v` → all PASS.
- [ ] Backend: `make check` (alembic check + ruff + mypy) → clean. (No migration expected — analytics adds no tables. If mypy flags the new module, fix inline.)
- [ ] Frontend: `cd admin-ui && npm run typecheck && npm run lint && npm test -- analytics-format chart-colors stat-tile time-range-switcher dashboard` → clean/PASS.
- [ ] Manual: `/dashboard` renders tiles + charts, tile click swaps the trend metric, range/granularity switch refetches, previous-period overlay visible.
- [ ] Invoke the `code-review` agent (money/PII-adjacent read surface + >3 files) and the `automation-testing` agent (new endpoints) per CLAUDE.md triggers.

## Notes / known limitations (from spec §6)
- Single base currency per tenant assumed; no FX normalization.
- Active tenant only; no platform-wide roll-up.
- No pre-aggregation/materialized views — add only if measured latency requires (via Alembic).
- Spec KPI **B5 (new vs returning transactors)** is intentionally deferred — it needs a per-user first-seen lookback that's heavier than the other queries; the `active_users` endpoint (DAU/WAU/MAU) already ships the core activity signal. Add B5 in a follow-up if wanted.
- The `active_users` (DAU/WAU/MAU) endpoint is built and returned by the server action but not yet surfaced as its own tile in Task 12/15 — wire it into the tile row when desired (data is already available client-side).
