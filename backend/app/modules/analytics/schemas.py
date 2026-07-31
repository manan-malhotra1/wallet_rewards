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
