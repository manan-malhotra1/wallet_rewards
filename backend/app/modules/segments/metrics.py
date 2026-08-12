"""Metric registry for dynamic segments — name → set-based value builder.

Every builder computes ONE aggregate per tenant as {user_id: Decimal},
covering all users of the tenant in a single query (no per-user loops).
Adding a metric = add a builder here + the name in criteria.MetricName;
tests/segments/test_metrics.py::test_registry_matches_dsl_vocabulary
enforces the two stay in sync (a module-level assert would be stripped
under `python -O`, so the test is the sole source of truth for this).

Attribution semantics (v1): Transaction metrics are wallet-attributed: they
measure COMPLETED transactions that touched the user's own financial wallet
(send and receive), NOT transactions the user initiated. `Transaction.
initiated_by` is the wrong join key for a user-facing metric — it mis-attributes
cash-in to the agent (see `cashin/service.py`, whose `RewardTrigger`
deliberately targets the customer instead), gives P2P *recipients* no row at
all, and is NULL on system-initiated inbound activity (e.g. remittance). Every
transactional builder therefore joins Account (the user's `financial_wallet`)
-> LedgerEntry (COMPLETED, on that wallet) -> Transaction (same tenant,
COMPLETED) and groups by `Account.user_id`; see `_wallet_txn_base`. `txn_sum`
is additionally scoped to the tenant's base currency (a user with wallets in
more than one currency must not have them silently added together — same rule
as `wallet_balance`); `txn_count` and `days_since_last_txn` stay
currency-agnostic (a transaction count/recency is meaningful across
currencies, a summed amount is not). This is recorded in
`docs/superpowers/specs/2026-08-12-ai-segmentation-design.md` §3.

Shared builder contract:
  - Every entry in `METRIC_BUILDERS` is an async, set-based aggregate — see
    the `MetricBuilder` protocol below for the exact call shape.
  - `txn_type` / `window_days` are accepted by every builder even when
    inapplicable (only transactional/windowed metrics use them) — builders
    that ignore a filter swallow it via `**_: object` rather than each
    caller needing to know which metrics support which filters.
  - `now` is the evaluation instant for every relative-time computation
    (rolling windows, account age, recency). `compute_metric` computes it
    ONCE (default: the current UTC instant) and passes the identical value
    into every builder, so a single metric run — and, in tests, an explicit
    `now` — is internally consistent and reproducible.
  - Return value omits users with zero contribution; callers default a
    missing user to `Decimal(0)` — EXCEPT `days_since_last_txn`, which
    already fills in every tenant user, using the `NEVER_TRANSACTED_DAYS`
    sentinel for those with no wallet-touching COMPLETED transaction.
  - Every returned user_id belongs to `tenant_id` — no builder ever leaks a
    key from another tenant into the map.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.modules.ledger.service import signed_balance_expr
from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ENTRY_STATUS_COMPLETED,
    REDEMPTION_STATUS_COMPLETED,
    REFERRAL_STATUS_REWARDED,
    TXN_STATUS_COMPLETED,
    Account,
    LedgerEntry,
    Redemption,
    Referral,
    RewardEvent,
    Tenant,
    Transaction,
    User,
)

# Sentinel for `days_since_last_txn` on a user with no wallet-touching
# COMPLETED transaction. Deliberately far larger than any realistic dormancy
# threshold: a `gte`-style "inactive for N+ days" condition must INCLUDE
# never-transacted users (they are maximally dormant), which this sentinel
# satisfies for any sane N; a `lte`/`eq` "active within N days" condition must
# EXCLUDE them, which it also does by being far outside any such bound.
NEVER_TRANSACTED_DAYS = Decimal(99999)


class MetricBuilder(Protocol):
    """Structural contract every `METRIC_BUILDERS` entry must satisfy.

    Declared as a Protocol (rather than `Callable[..., ...]`) so mypy checks
    the actual keyword shape every builder is called with, instead of
    accepting any callable regardless of signature.
    """

    async def __call__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        txn_type: str | None = None,
        window_days: int | None = None,
        now: datetime,
    ) -> dict[UUID, Decimal]: ...


def _window_start(now: datetime, window_days: int | None) -> datetime | None:
    """Lower created_at bound for a rolling window, or None for lifetime.

    Args:
        now: Evaluation instant (see module docstring — shared across a run).
        window_days: Rolling window length in days, or None for no bound.

    Returns:
        `now - window_days` days, or None when `window_days` is None.
    """
    if window_days is None:
        return None
    return now - timedelta(days=window_days)


def _days_since(now: datetime, timestamp: Any) -> ColumnElement[Any]:
    """Days between a bound `now` parameter and a timestamp column/aggregate.

    Uses `literal(now)` (a bound SQL parameter) rather than `func.now()` so
    every relative-time metric in one evaluation run — and, in tests, an
    explicit `now` — measures from the identical instant (see module
    docstring's "Shared builder contract").
    """
    return func.extract("epoch", literal(now) - timestamp) / 86400


async def _rows_to_map(session: AsyncSession, stmt: Select[Any]) -> dict[UUID, Decimal]:
    """Execute a (user_id, value) select into a {user_id: Decimal} map.

    Args:
        session: Async DB session.
        stmt: A SELECT yielding exactly two columns: user_id, aggregate value.

    Returns:
        Mapping of user_id to Decimal value, skipping any NULL user_id rows.
    """
    result = await session.execute(stmt)
    # Decimal(str(x)) — never Decimal(float) directly — defense-in-depth for
    # this generic helper: asyncpg already returns Decimal for NUMERIC/EXTRACT
    # results on the Postgres version this repo targets, so today every caller
    # gets a Decimal-safe round trip either way, but a future builder could
    # select a genuinely float-typed column, and Decimal(0.1) != Decimal("0.1")
    # (binary float representation — same reason criteria.py's comparator
    # handling goes through str() first).
    return {row[0]: Decimal(str(row[1])) for row in result.all() if row[0] is not None}


def _wallet_txn_base(tenant_id: UUID) -> Select[Any]:
    """Shared join: a user's financial wallet -> its COMPLETED transactions.

    This is the wallet-attribution join described in the module docstring:
    Account (financial_wallet, this tenant) -> LedgerEntry (COMPLETED, the
    wallet's own entry — either leg, DEBIT or CREDIT) -> Transaction (same
    tenant, COMPLETED) by `transaction_id`. Callers `.add_columns(...)` their
    own aggregate, apply any `transaction_type` / window filter on
    `Transaction`, and `.group_by(Account.user_id)`.

    At-scale measurement (segmentation Task 5, follow-up to migration 0054's
    docstring): EXPLAIN ANALYZE on a synthetic 500k-row `ledger_entries` table
    (5k accounts, 250k transactions, one tenant) for the `txn_count` query
    compared plain vs. with a candidate covering index `ledger_entries
    (status, created_at) INCLUDE (account_id, transaction_id, amount)`
    created in the same session. Both runs produced the IDENTICAL plan
    (`Seq Scan on ledger_entries` + hash joins, cost `0.00..13394.33`) — the
    planner never chose the new index at all; the identical plan is itself
    the proof, no timing comparison needed. Two durable reasons this
    candidate shape loses, neither specific to this synthetic data mix:
    (a) NOTHING in this module ever filters on `LedgerEntry.created_at`
    (grep-verified — the window filter in `txn_count`/`txn_sum` applies to
    `Transaction.created_at`, one join hop away), so the index's second
    column can never narrow a scan here, in any tenant's data; (b)
    `INCLUDE (account_id, transaction_id, amount)` makes each index tuple
    nearly as wide as the heap row it covers, so even an index-only scan
    saves little I/O on a query that (with no window bound) aggregates the
    WHOLE table anyway. Conclusion: THIS candidate index shape is ruled
    out — no migration added. Migration 0054's broader question (does the
    LedgerEntry leg need ITS OWN tuning at all) stays open; the shape worth
    measuring next is an ACCOUNT-leading index — `ix_ledger_entries_account
    (account_id, status, created_at)` already exists, so the next step is
    checking whether the planner will use IT once accounts-per-tenant is
    large enough to make a per-account index probe cheaper than the hash
    join chosen here, not inventing a new index shape. Caveat: this was a
    SINGLE tenant's synthetic data; it says nothing about a many-tenant
    sweep (`_recompute_all` in `segments/tasks.py` runs this query once per
    tenant, sequentially) where cross-tenant contention/cache pressure could
    behave differently — not measured here.

    Returns:
        A SELECT of `Account.user_id` with the join and base filters applied,
        ready for `.add_columns(...)`.
    """
    return (
        select(Account.user_id)
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .join(Transaction, Transaction.id == LedgerEntry.transaction_id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == ACCOUNT_TYPE_FINANCIAL_WALLET,
            Account.user_id.is_not(None),
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
            Transaction.tenant_id == tenant_id,
            Transaction.status == TXN_STATUS_COMPLETED,
        )
    )


async def txn_count(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
    now: datetime,
) -> dict[UUID, Decimal]:
    """Wallet-attributed COMPLETED transaction count per user (see module docstring)."""
    stmt = _wallet_txn_base(tenant_id).add_columns(
        func.count(func.distinct(LedgerEntry.transaction_id))
    )
    if txn_type is not None:
        stmt = stmt.where(Transaction.transaction_type == txn_type)
    start = _window_start(now, window_days)
    if start is not None:
        stmt = stmt.where(Transaction.created_at >= start)
    stmt = stmt.group_by(Account.user_id)
    return await _rows_to_map(session, stmt)


async def txn_sum(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    txn_type: str | None = None,
    window_days: int | None = None,
    now: datetime,
) -> dict[UUID, Decimal]:
    """Wallet-attributed gross transaction value per user, base-currency scoped.

    Definition: SUM(LedgerEntry.amount) over every COMPLETED entry that
    touches the user's financial wallet — send AND receive AND fee legs all
    count (this is gross value moved through the wallet, not net flow; a
    dedicated net-flow metric would need to sign the sum by entry_type, which
    v1 does not do — see module docstring).

    Scoped to `Tenant.base_currency` (same rule as `wallet_balance`): a user
    who holds wallets in more than one currency must not have those amounts
    silently summed together. `txn_count` and `days_since_last_txn` are NOT
    currency-scoped — counting/timing a transaction is meaningful regardless
    of currency, only a summed amount is not.
    """
    base_currency = select(Tenant.base_currency).where(Tenant.id == tenant_id).scalar_subquery()
    stmt = _wallet_txn_base(tenant_id).add_columns(func.coalesce(func.sum(LedgerEntry.amount), 0))
    stmt = stmt.where(LedgerEntry.currency == base_currency)
    if txn_type is not None:
        stmt = stmt.where(Transaction.transaction_type == txn_type)
    start = _window_start(now, window_days)
    if start is not None:
        stmt = stmt.where(Transaction.created_at >= start)
    stmt = stmt.group_by(Account.user_id)
    return await _rows_to_map(session, stmt)


async def _balance(
    session: AsyncSession,
    tenant_id: UUID,
    account_type: str,
    *,
    currency: ColumnElement[Any] | str | None = None,
) -> dict[UUID, Decimal]:
    """Signed COMPLETED ledger sum per user for one account type.

    Uses the shared `ledger.service.signed_balance_expr` (CREDIT +, DEBIT -)
    across every user account of the tenant in one query.

    Account status is deliberately NOT filtered — a suspended/closed wallet's
    balance still counts, matching `analytics._account_type_balance_by_currency`.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope the query to (NFR-0220).
        account_type: One of the `ACCOUNT_TYPE_*` constants to sum over.
        currency: Optional currency filter (column, scalar subquery, or
            literal). Balances must NEVER be summed across currencies
            (documented invariant in `analytics/service.py`); pass this for
            any account type that can hold more than one currency.

    Returns:
        Mapping of user_id to net Decimal balance for that account type.
    """
    stmt = (
        select(Account.user_id, func.coalesce(func.sum(signed_balance_expr()), 0))
        .join(LedgerEntry, LedgerEntry.account_id == Account.id)
        .where(
            Account.tenant_id == tenant_id,
            Account.account_type == account_type,
            Account.user_id.is_not(None),
            LedgerEntry.status == ENTRY_STATUS_COMPLETED,
        )
        .group_by(Account.user_id)
    )
    if currency is not None:
        stmt = stmt.where(Account.currency == currency)
    return await _rows_to_map(session, stmt)


async def wallet_balance(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Financial-wallet balance per user, scoped to the tenant's base currency.

    A tenant may in principle provision wallets in more than one currency;
    balances are NEVER summed across currencies, so this filters to
    `Tenant.base_currency` via a scalar subquery (one query, no extra
    round-trip) rather than mixing ZAR and USD wallets into one number.
    """
    base_currency = select(Tenant.base_currency).where(Tenant.id == tenant_id).scalar_subquery()
    return await _balance(session, tenant_id, ACCOUNT_TYPE_FINANCIAL_WALLET, currency=base_currency)


async def points_balance(
    session: AsyncSession, tenant_id: UUID, **_: object
) -> dict[UUID, Decimal]:
    """Points-account balance per user.

    Not currency-scoped: every points account is provisioned in the single
    fixed "PTS" currency code platform-wide (see the points-instrument
    provisioning in `app/modules/tenants/service.py`), so there is no
    cross-currency mixing to guard against here.
    """
    return await _balance(session, tenant_id, ACCOUNT_TYPE_POINTS)


async def points_redeemed(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    window_days: int | None = None,
    now: datetime,
    **_: object,
) -> dict[UUID, Decimal]:
    """COMPLETED redemption points per user."""
    stmt = (
        select(Redemption.user_id, func.coalesce(func.sum(Redemption.points_amount), 0))
        .where(Redemption.tenant_id == tenant_id, Redemption.status == REDEMPTION_STATUS_COMPLETED)
        .group_by(Redemption.user_id)
    )
    start = _window_start(now, window_days)
    if start is not None:
        stmt = stmt.where(Redemption.created_at >= start)
    return await _rows_to_map(session, stmt)


async def rewards_earned(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    window_days: int | None = None,
    now: datetime,
    **_: object,
) -> dict[UUID, Decimal]:
    """Reward events per user. Counts reward events, not points value.

    Tenant-scoped via a User join — `RewardEvent` carries no `tenant_id`.
    """
    stmt = (
        select(RewardEvent.user_id, func.count())
        .join(User, User.id == RewardEvent.user_id)
        .where(User.tenant_id == tenant_id)
        .group_by(RewardEvent.user_id)
    )
    start = _window_start(now, window_days)
    if start is not None:
        stmt = stmt.where(RewardEvent.created_at >= start)
    return await _rows_to_map(session, stmt)


async def account_age_days(
    session: AsyncSession, tenant_id: UUID, *, now: datetime, **_: object
) -> dict[UUID, Decimal]:
    """Days since signup per user, measured from the shared `now`."""
    stmt = select(User.id, _days_since(now, User.created_at)).where(User.tenant_id == tenant_id)
    return await _rows_to_map(session, stmt)


async def days_since_last_txn(
    session: AsyncSession, tenant_id: UUID, *, now: datetime, **_: object
) -> dict[UUID, Decimal]:
    """Days since the user's last wallet-touching COMPLETED transaction.

    Wallet-attributed like `txn_count`/`txn_sum` (see module docstring) — no
    `transaction_type` filter applies here. Users with no such transaction get
    the `NEVER_TRANSACTED_DAYS` sentinel rather than being omitted.
    """
    stmt = _wallet_txn_base(tenant_id).add_columns(
        _days_since(now, func.max(Transaction.created_at))
    )
    stmt = stmt.group_by(Account.user_id)
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


METRIC_BUILDERS: dict[str, MetricBuilder] = {
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
    now: datetime | None = None,
) -> dict[UUID, Decimal]:
    """Dispatch one metric computation to its registered builder.

    Args:
        session: Async DB session.
        tenant_id: Tenant to scope the computation to (NFR-0220).
        metric: A key of `METRIC_BUILDERS` (kept in sync with `criteria.MetricName`).
        txn_type: Forwarded to transactional metrics; ignored by others.
        window_days: Forwarded to windowed metrics; ignored by others.
        now: Evaluation instant for every relative-time computation. Defaults
            to the current UTC instant, computed ONCE here (not per builder)
            so a single metric run is internally consistent; pass an explicit
            value for reproducible/deterministic results (e.g. in tests).

    Returns:
        Mapping of user_id to the metric's Decimal value (see the module
        docstring's "Shared builder contract" for zero-omission/sentinel
        semantics).

    Raises:
        KeyError: `metric` is not a registered builder name.
    """
    effective_now = now or datetime.now(UTC)
    return await METRIC_BUILDERS[metric](
        session, tenant_id, txn_type=txn_type, window_days=window_days, now=effective_now
    )
