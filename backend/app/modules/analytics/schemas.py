"""Pydantic v2 response models for the analytics endpoints.

Each model is a plain read DTO. `current`/`previous` pairs let the frontend
compute day-on-day / week-on-week deltas without a second round-trip.

Money metrics are ALWAYS grouped by currency and NEVER summed or converted
across currencies — a tenant may run several currencies at once, and ZAR + MGA
have no common denominator. Count / user / points metrics stay
currency-agnostic. See CLAUDE.md and the analytics service docstrings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ScalarWithPrevious(BaseModel):
    """A single headline number plus its previous-period value.

    The frontend derives the delta % (current vs previous) for the tile chip.
    Used for currency-agnostic scalars only (counts, users, points).
    """

    current: Decimal
    previous: Decimal


class CurrencyInfo(BaseModel):
    """A tenant currency (money instrument) for the dashboard currency toggle."""

    code: str
    symbol: str
    display_name: str


class CurrencyScalar(BaseModel):
    """A per-currency headline value + its previous-period value."""

    currency: str
    current: Decimal
    previous: Decimal


class BucketAmount(BaseModel):
    """A money value for one time bucket."""

    bucket: datetime
    value: Decimal


class CurrencySeries(BaseModel):
    """A per-currency bucketed money series, current + aligned previous."""

    currency: str
    current: list[BucketAmount]
    previous: list[BucketAmount]


class CountPoint(BaseModel):
    """A currency-agnostic count for one time bucket."""

    bucket: datetime
    count: int


class CountSeries(BaseModel):
    """Currency-agnostic bucketed counts, current + aligned previous."""

    current: list[CountPoint]
    previous: list[CountPoint]


class MetricsTimeseries(BaseModel):
    """Trend data for the shared chart: agnostic count + per-currency volume & revenue."""

    count: CountSeries
    volume: list[CurrencySeries]
    revenue: list[CurrencySeries]


class DashboardSummary(BaseModel):
    """All stat-tile scalars for the selected range, current + previous period.

    One round-trip populates the top tile row across KPI groups A/B/D/E. Money
    tiles (`transaction_volume`, `avg_transaction_value`, `revenue_total`) are
    per-currency lists — the frontend renders one figure per active currency and
    never sums them. Count / user / points tiles stay single scalars.
    """

    transaction_count: ScalarWithPrevious
    transaction_volume: list[CurrencyScalar]
    avg_transaction_value: list[CurrencyScalar]
    revenue_total: list[CurrencyScalar]
    new_users: ScalarWithPrevious
    total_users: Decimal
    active_users_period: Decimal
    points_issued: ScalarWithPrevious
    points_redeemed: ScalarWithPrevious


class ServiceSlice(BaseModel):
    """Transaction count + value for one transaction_type (service).

    Currency-agnostic COUNT donut. `volume` is retained as a rough size hint but
    is NOT a cross-currency money figure the UI should total.
    """

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


class RevenueServiceSlice(BaseModel):
    """Per-currency revenue components for one transaction_type. total = fee (operator revenue)."""

    service_type: str
    currency: str
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


class CurrencyLiquidity(BaseModel):
    """Per-currency wallet float liability + cash-float balance."""

    currency: str
    wallet_liability: Decimal
    cash_float_balance: Decimal


class NetFlowPoint(BaseModel):
    """Wallet and treasury flow for one bucket, per currency.

    Two independent pairs, deliberately NOT summed together:

    * `inflow` / `outflow` — money crossing the USER WALLET boundary. An internal
      transfer (p2p, cashout, cash_in) touches two user wallets and so raises both
      sides equally; only funding, airtime and withdrawals move the net.
    * `treasury_inflow` / `treasury_outflow` — OPERATOR cash movements between the
      cash float and the bank (`treasury.adjust`). These never touch a user wallet,
      which is why an operator withdrawal was previously invisible here.

    Keeping them apart matters: adding an operator float top-up to customer inflow
    would read as customer activity that never happened.
    """

    bucket: datetime
    currency: str
    inflow: Decimal
    outflow: Decimal
    treasury_inflow: Decimal = Decimal("0")
    treasury_outflow: Decimal = Decimal("0")


class UserTypeSlice(BaseModel):
    """User count for one user_type."""

    user_type: str
    count: int
