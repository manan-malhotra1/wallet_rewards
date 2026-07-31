"""API tests for the analytics dashboard endpoints.

Covers, across the eight read-only `/api/v1/analytics/` endpoints: happy path,
auth failure (401), permission failure (403), bad-parameter rejection (422),
tenant isolation, empty-range no-crash, and aggregation correctness (by-service
grouping, revenue sums, distinct active users, and points issued via the
RewardEvent → Rule tenant-scoped join).

Analytics endpoints are read-only, so there is no idempotency-key surface to
exercise. Rows are seeded directly against the test DB (no prefund float, so the
aggregation counts are exactly what each test creates).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import (
    ACCOUNT_TYPE_FINANCIAL_WALLET,
    ACCOUNT_TYPE_POINTS,
    ENTRY_CREDIT,
    ENTRY_STATUS_COMPLETED,
    REWARD_TYPE_POINTS,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    Account,
    Instrument,
    LedgerEntry,
    RewardEvent,
    Rule,
    Tenant,
    Transaction,
    User,
)

# Every analytics endpoint, with the extra query params it needs beyond
# `tenant_id`. Drives the parametrised auth + empty-tenant happy-path sweeps so
# no endpoint is left uncovered.
ANALYTICS_ENDPOINTS = [
    ("/api/v1/analytics/currencies", {}),
    ("/api/v1/analytics/summary", {}),
    ("/api/v1/analytics/transactions/timeseries", {"granularity": "day"}),
    ("/api/v1/analytics/transactions/by-service", {}),
    ("/api/v1/analytics/transactions/by-status", {"granularity": "day"}),
    ("/api/v1/analytics/users/timeseries", {"granularity": "day"}),
    ("/api/v1/analytics/users/active", {}),
    ("/api/v1/analytics/revenue/by-service", {}),
    ("/api/v1/analytics/rewards/timeseries", {"granularity": "day"}),
    ("/api/v1/analytics/liquidity", {}),
    ("/api/v1/analytics/net-flow", {"granularity": "day"}),
    ("/api/v1/analytics/users/by-type", {}),
]


# -----------------------------------------------------------------------------
# Seed helpers — write rows directly (analytics is read-only).
# -----------------------------------------------------------------------------


async def _make_tenant(db_session: AsyncSession, *, name: str) -> Tenant:
    """Create a bare tenant with no prefund float, so no stray transactions."""
    tenant = Tenant(name=name, business_type="both", base_currency="ZAR")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


async def _make_user(db_session: AsyncSession, tenant: Tenant) -> User:
    """Create a minimal active user (satisfies the initiated_by FK)."""
    user = User(tenant_id=tenant.id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_txn(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    txn_type: str,
    amount: Decimal,
    status: str = TXN_STATUS_COMPLETED,
    fee: Decimal = Decimal("0"),
    tax: Decimal = Decimal("0"),
    commission: Decimal = Decimal("0"),
    currency: str = "ZAR",
    initiated_by: User | None = None,
    created_at: datetime | None = None,
) -> Transaction:
    """Insert one transaction with a unique idempotency key inside the window.

    Defaults `created_at` to one day ago so the row lands inside the default 7d
    current window used by every endpoint's default `range`. `currency` defaults
    to ZAR; pass a second currency (e.g. MGA) to prove money is never summed.
    """
    txn = Transaction(
        tenant_id=tenant.id,
        idempotency_key=uuid4().hex,
        transaction_type=txn_type,
        status=status,
        amount=amount,
        fee_amount=fee,
        tax_amount=tax,
        commission_amount=commission,
        currency=currency,
        initiated_by=initiated_by.id if initiated_by else None,
        created_at=created_at or (datetime.now(UTC) - timedelta(days=1)),
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    return txn


async def _issue_points(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    value: Decimal,
) -> RewardEvent:
    """Seed a points RewardEvent joined to a tenant-scoped Rule.

    `reward_events` has no tenant_id — the analytics service scopes it via the
    Rule join, so this exercises that join end-to-end. `created_at` is one day
    ago so it falls inside the default current window.
    """
    rule = Rule(
        tenant_id=tenant.id,
        name=f"rule-{uuid4().hex[:8]}",
        rule_type="first_time",
        reward_type="points",
        reward_value=value,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    event = RewardEvent(
        user_id=user.id,
        rule_id=rule.id,
        triggering_event_id=uuid4().hex,
        reward_type=REWARD_TYPE_POINTS,
        reward_value=value,
        multiplier_applied=Decimal("1"),
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


async def _make_typed_user(db_session: AsyncSession, tenant: Tenant, *, user_type: str) -> User:
    """Create a user with an explicit user_type (consumer / agent / merchant…)."""
    user = User(tenant_id=tenant.id, user_type=user_type)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_instrument(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    code: str,
    symbol: str,
    display_name: str,
    account_type: str = ACCOUNT_TYPE_FINANCIAL_WALLET,
) -> Instrument:
    """Seed one active instrument (a currency or a points unit) for the tenant."""
    instrument = Instrument(
        tenant_id=tenant.id,
        code=code,
        symbol=symbol,
        display_name=display_name,
        account_type=account_type,
    )
    db_session.add(instrument)
    await db_session.commit()
    await db_session.refresh(instrument)
    return instrument


async def _make_wallet_credit(
    db_session: AsyncSession,
    tenant: Tenant,
    user: User,
    *,
    amount: Decimal,
    currency: str = "ZAR",
    created_at: datetime | None = None,
) -> LedgerEntry:
    """Seed a COMPLETED CREDIT on a user financial_wallet account.

    Creates the parent Transaction (LedgerEntry.transaction_id is a non-null
    FK) and the wallet Account, then the credit entry — so both liquidity
    (wallet_liability) and net-flow (inflow) aggregations have real rows to
    read. `created_at` defaults inside the default 7d window; `currency`
    defaults to ZAR.
    """
    txn = await _make_txn(db_session, tenant, txn_type="cashin", amount=amount, currency=currency)
    account = Account(
        tenant_id=tenant.id,
        user_id=user.id,
        account_type=ACCOUNT_TYPE_FINANCIAL_WALLET,
        currency=currency,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    entry = LedgerEntry(
        transaction_id=txn.id,
        account_id=account.id,
        entry_type=ENTRY_CREDIT,
        amount=amount,
        currency=currency,
        status=ENTRY_STATUS_COMPLETED,
        created_at=created_at or (datetime.now(UTC) - timedelta(days=1)),
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    return entry


# -----------------------------------------------------------------------------
# Auth + happy-path sweeps across every endpoint
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path,extra", ANALYTICS_ENDPOINTS)
async def test_analytics_endpoint_requires_authentication(
    async_client: AsyncClient,
    db_session: AsyncSession,
    path: str,
    extra: dict[str, str],
) -> None:
    """Verify an unauthenticated caller cannot read any dashboard metric"""
    tenant = await _make_tenant(db_session, name="auth-401")
    response = await async_client.get(path, params={"tenant_id": str(tenant.id), **extra})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path,extra", ANALYTICS_ENDPOINTS)
async def test_analytics_endpoint_rejects_a_non_finance_admin(
    async_client: AsyncClient,
    db_session: AsyncSession,
    make_admin_token,
    path: str,
    extra: dict[str, str],
) -> None:
    """Verify an admin without finance access is denied the dashboard metrics"""
    tenant = await _make_tenant(db_session, name="auth-403")
    token = make_admin_token(roles=["user-approver"])  # not finance-reviewer / platform-admin
    response = await async_client.get(
        path,
        params={"tenant_id": str(tenant.id), **extra},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "insufficient_role"


@pytest.mark.asyncio
@pytest.mark.parametrize("path,extra", ANALYTICS_ENDPOINTS)
async def test_analytics_endpoint_returns_zeros_for_a_brand_new_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
    path: str,
    extra: dict[str, str],
) -> None:
    """Verify every dashboard metric loads with empty results for a new tenant"""
    tenant = await _make_tenant(db_session, name=f"empty-{path.rsplit('/', 1)[-1]}")
    response = await async_client.get(
        path,
        params={"tenant_id": str(tenant.id), **extra},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_finance_reviewer_can_read_the_dashboard(
    async_client: AsyncClient,
    db_session: AsyncSession,
    make_admin_token,
) -> None:
    """Verify a finance reviewer (not a platform admin) can read the dashboard"""
    tenant = await _make_tenant(db_session, name="finance-ok")
    token = make_admin_token(roles=["finance-reviewer"])
    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


# -----------------------------------------------------------------------------
# Bad-parameter (422) and empty-range shape
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_rejects_an_unknown_range(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a nonsense date range is rejected instead of silently guessed"""
    tenant = await _make_tenant(db_session, name="bad-range")
    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant.id), "range": "all-time"},
        headers=admin_auth_header,
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_timeseries_rejects_an_unknown_granularity(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify an unsupported bucket size is rejected on a timeseries request"""
    tenant = await _make_tenant(db_session, name="bad-gran")
    response = await async_client.get(
        "/api/v1/analytics/transactions/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "hourly"},
        headers=admin_auth_header,
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_transactions_timeseries_zero_fills_a_brand_new_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a new tenant's chart returns dense, aligned zero-filled counts"""
    tenant = await _make_tenant(db_session, name="empty-ts")
    response = await async_client.get(
        "/api/v1/analytics/transactions/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    current, previous = body["count"]["current"], body["count"]["previous"]
    # Dense zero-fill: both count series present, equal-length, every point zeroed.
    assert len(current) > 0
    assert len(current) == len(previous)
    # A 7d/day window truncates to 7 or 8 day-buckets depending on where `now`
    # falls within its day.
    assert 7 <= len(current) <= 8
    for point in current + previous:
        assert point["count"] == 0
    # No transactions → no currency has activity → empty money series.
    assert body["volume"] == []
    assert body["revenue"] == []


# -----------------------------------------------------------------------------
# Tenant isolation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_isolates_one_tenants_activity_from_another(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant's dashboard never counts another tenant's transactions"""
    tenant_a = await _make_tenant(db_session, name="iso-A")
    tenant_b = await _make_tenant(db_session, name="iso-B")
    # All activity belongs to tenant A.
    await _make_txn(db_session, tenant_a, txn_type="cashin", amount=Decimal("100"))
    await _make_txn(db_session, tenant_a, txn_type="cashin", amount=Decimal("250"))

    # Tenant B's summary must show none of it.
    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant_b.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["transaction_count"]["current"]) == 0
    # Per-currency money list: no activity → no currency rows at all.
    assert body["transaction_volume"] == []

    # Tenant B's by-service view is likewise empty.
    by_service = await async_client.get(
        "/api/v1/analytics/transactions/by-service",
        params={"tenant_id": str(tenant_b.id)},
        headers=admin_auth_header,
    )
    assert by_service.status_code == 200, by_service.text
    assert by_service.json() == []


# -----------------------------------------------------------------------------
# Aggregation correctness
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_totals_the_completed_transactions_in_the_range(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the headline count and volume sum only completed transactions"""
    tenant = await _make_tenant(db_session, name="sum-total")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("100"))
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("300"))
    # A failed transaction must NOT be counted in count / volume.
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("999"), status=TXN_STATUS_FAILED
    )

    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Count stays currency-agnostic; money is a per-currency list (all ZAR here).
    assert Decimal(body["transaction_count"]["current"]) == 2
    volume = {row["currency"]: row for row in body["transaction_volume"]}
    avg = {row["currency"]: row for row in body["avg_transaction_value"]}
    assert Decimal(volume["ZAR"]["current"]) == Decimal("400")
    assert Decimal(avg["ZAR"]["current"]) == Decimal("200")


@pytest.mark.asyncio
async def test_by_service_groups_and_sums_per_service_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the service mix groups transactions and sums volume per service"""
    tenant = await _make_tenant(db_session, name="by-service")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("100"))
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("150"))
    await _make_txn(db_session, tenant, txn_type="airtime", amount=Decimal("40"))

    response = await async_client.get(
        "/api/v1/analytics/transactions/by-service",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    slices = {row["service_type"]: row for row in response.json()}
    assert slices["cashin"]["count"] == 2
    assert Decimal(slices["cashin"]["volume"]) == Decimal("250")
    assert slices["airtime"]["count"] == 1
    assert Decimal(slices["airtime"]["volume"]) == Decimal("40")


@pytest.mark.asyncio
async def test_revenue_by_service_sums_fee_tax_and_commission(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify per-service operator revenue is the fee only, tax and commission excluded"""
    tenant = await _make_tenant(db_session, name="revenue")
    await _make_txn(
        db_session,
        tenant,
        txn_type="cashout",
        amount=Decimal("100"),
        fee=Decimal("5"),
        tax=Decimal("1"),
        commission=Decimal("2"),
    )
    await _make_txn(
        db_session,
        tenant,
        txn_type="cashout",
        amount=Decimal("100"),
        fee=Decimal("3"),
        tax=Decimal("1"),
        commission=Decimal("0"),
    )

    response = await async_client.get(
        "/api/v1/analytics/revenue/by-service",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    row = next(r for r in response.json() if r["service_type"] == "cashout")
    assert Decimal(row["fee"]) == Decimal("8")
    assert Decimal(row["tax"]) == Decimal("2")
    assert Decimal(row["commission"]) == Decimal("2")
    # Operator revenue = fee only; tax is a pass-through, commission an agent cost.
    assert Decimal(row["total"]) == Decimal("8")


@pytest.mark.asyncio
async def test_by_status_buckets_count_each_status(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the status breakdown counts completed, failed and pending rows"""
    tenant = await _make_tenant(db_session, name="by-status")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("10"))
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("10"))
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("10"), status=TXN_STATUS_FAILED
    )
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("10"), status=TXN_STATUS_PENDING
    )

    response = await async_client.get(
        "/api/v1/analytics/transactions/by-status",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    buckets = response.json()
    assert sum(b["completed"] for b in buckets) == 2
    assert sum(b["failed"] for b in buckets) == 1
    assert sum(b["pending"] for b in buckets) == 1


@pytest.mark.asyncio
async def test_active_users_counts_distinct_transactors(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify active-user counts reflect distinct people who transacted"""
    tenant = await _make_tenant(db_session, name="active")
    user_one = await _make_user(db_session, tenant)
    user_two = await _make_user(db_session, tenant)
    # user_one transacts twice, user_two once → 2 distinct transactors.
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("10"), initiated_by=user_one
    )
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("20"), initiated_by=user_one
    )
    await _make_txn(
        db_session, tenant, txn_type="cashin", amount=Decimal("30"), initiated_by=user_two
    )

    response = await async_client.get(
        "/api/v1/analytics/users/active",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mau"] == 2
    assert body["wau"] == 2


# -----------------------------------------------------------------------------
# Rewards path — exercises the RewardEvent → Rule tenant-scoped join
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewards_timeseries_returns_zero_liability_without_events(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the rewards chart loads with zero liability when nothing was issued"""
    tenant = await _make_tenant(db_session, name="rewards-empty")
    response = await async_client.get(
        "/api/v1/analytics/rewards/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["points"] == []
    assert Decimal(body["outstanding_liability"]) == 0


@pytest.mark.asyncio
async def test_summary_and_rewards_reflect_points_issued(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify issued reward points surface in both the summary and rewards chart"""
    tenant = await _make_tenant(db_session, name="rewards-issued")
    user = await _make_user(db_session, tenant)
    await _issue_points(db_session, tenant, user, value=Decimal("500"))
    await _issue_points(db_session, tenant, user, value=Decimal("250"))

    summary = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert summary.status_code == 200, summary.text
    assert Decimal(summary.json()["points_issued"]["current"]) == Decimal("750")

    rewards = await async_client.get(
        "/api/v1/analytics/rewards/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert rewards.status_code == 200, rewards.text
    body = rewards.json()
    assert Decimal(body["outstanding_liability"]) == Decimal("750")
    assert sum(Decimal(p["issued"]) for p in body["points"]) == Decimal("750")


@pytest.mark.asyncio
async def test_reward_points_are_scoped_to_the_owning_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify one tenant's issued points never appear on another tenant's dashboard"""
    tenant_a = await _make_tenant(db_session, name="rewards-iso-A")
    tenant_b = await _make_tenant(db_session, name="rewards-iso-B")
    user_a = await _make_user(db_session, tenant_a)
    await _issue_points(db_session, tenant_a, user_a, value=Decimal("400"))

    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant_b.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["points_issued"]["current"]) == 0


# -----------------------------------------------------------------------------
# Liquidity — wallet float liability from the ledger
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_liquidity_reflects_the_user_wallet_float(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the liquidity view shows what users hold in their wallets"""
    tenant = await _make_tenant(db_session, name="liquidity")
    # Distinct users → distinct financial_wallet accounts (one wallet per
    # user/currency); the liability sums across all of them.
    user_one = await _make_user(db_session, tenant)
    user_two = await _make_user(db_session, tenant)
    await _make_wallet_credit(db_session, tenant, user_one, amount=Decimal("500"))
    await _make_wallet_credit(db_session, tenant, user_two, amount=Decimal("250"))

    response = await async_client.get(
        "/api/v1/analytics/liquidity",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    rows = {row["currency"]: row for row in response.json()}
    # Two COMPLETED credits into ZAR financial_wallet accounts → 750 liability.
    assert Decimal(rows["ZAR"]["wallet_liability"]) == Decimal("750")
    # No cash-float account was seeded → zero, not an error.
    assert Decimal(rows["ZAR"]["cash_float_balance"]) == 0


# -----------------------------------------------------------------------------
# Net flow — inflow vs outflow into user wallets
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_net_flow_reports_wallet_inflow(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify money credited into user wallets surfaces as inflow"""
    tenant = await _make_tenant(db_session, name="net-flow")
    user = await _make_user(db_session, tenant)
    await _make_wallet_credit(db_session, tenant, user, amount=Decimal("300"))

    response = await async_client.get(
        "/api/v1/analytics/net-flow",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    points = response.json()
    assert sum(Decimal(p["inflow"]) for p in points) == Decimal("300")
    assert sum(Decimal(p["outflow"]) for p in points) == 0


@pytest.mark.asyncio
async def test_net_flow_is_empty_for_a_brand_new_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a tenant with no ledger activity returns an empty net-flow series"""
    tenant = await _make_tenant(db_session, name="net-flow-empty")
    response = await async_client.get(
        "/api/v1/analytics/net-flow",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


# -----------------------------------------------------------------------------
# Users by type — distribution
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_users_by_type_requires_authentication(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify an unauthenticated caller cannot read the user-type distribution"""
    tenant = await _make_tenant(db_session, name="by-type-401")
    response = await async_client.get(
        "/api/v1/analytics/users/by-type",
        params={"tenant_id": str(tenant.id)},
    )
    assert response.status_code == 401


# -----------------------------------------------------------------------------
# Currencies endpoint + currency-awareness (money is NEVER summed across currencies)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_currencies_endpoint_lists_the_tenants_currencies(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the toggle lists the tenant's money currencies but not points"""
    tenant = await _make_tenant(db_session, name="currencies")
    await _make_instrument(db_session, tenant, code="ZAR", symbol="R", display_name="Rand")
    await _make_instrument(db_session, tenant, code="MGA", symbol="Ar", display_name="Ariary")
    # A points unit must NOT appear in the money-currency toggle.
    await _make_instrument(
        db_session,
        tenant,
        code="PTS",
        symbol="pt",
        display_name="Points",
        account_type=ACCOUNT_TYPE_POINTS,
    )

    response = await async_client.get(
        "/api/v1/analytics/currencies",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    codes = [row["code"] for row in response.json()]
    assert codes == ["MGA", "ZAR"]  # money only, ordered by code
    assert "PTS" not in codes


@pytest.mark.asyncio
async def test_currencies_endpoint_requires_authentication(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify an unauthenticated caller cannot read the currency list"""
    tenant = await _make_tenant(db_session, name="currencies-401")
    response = await async_client.get(
        "/api/v1/analytics/currencies",
        params={"tenant_id": str(tenant.id)},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_summary_never_sums_money_across_currencies(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify each currency's volume is reported separately, never merged into one total"""
    tenant = await _make_tenant(db_session, name="multi-ccy-summary")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("100"), currency="ZAR")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("50"), currency="MGA")

    response = await async_client.get(
        "/api/v1/analytics/summary",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    volume = {row["currency"]: Decimal(row["current"]) for row in body["transaction_volume"]}
    # A separate figure per currency — and crucially NOT a single 150.
    assert volume == {"ZAR": Decimal("100"), "MGA": Decimal("50")}
    assert Decimal("150") not in volume.values()
    revenue_ccys = {row["currency"] for row in body["revenue_total"]}
    assert revenue_ccys == {"ZAR", "MGA"}
    # Count stays currency-agnostic: the two transactions are one headline number.
    assert Decimal(body["transaction_count"]["current"]) == 2


@pytest.mark.asyncio
async def test_revenue_by_service_separates_currencies(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify per-service revenue is split per currency and never summed together"""
    tenant = await _make_tenant(db_session, name="multi-ccy-revenue")
    await _make_txn(
        db_session, tenant, txn_type="cashout", amount=Decimal("100"), fee=Decimal("5"),
        currency="ZAR",
    )
    await _make_txn(
        db_session, tenant, txn_type="cashout", amount=Decimal("100"), fee=Decimal("3"),
        currency="MGA",
    )

    response = await async_client.get(
        "/api/v1/analytics/revenue/by-service",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    rows = {(r["service_type"], r["currency"]): r for r in response.json()}
    assert Decimal(rows[("cashout", "ZAR")]["total"]) == Decimal("5")
    assert Decimal(rows[("cashout", "MGA")]["total"]) == Decimal("3")


@pytest.mark.asyncio
async def test_liquidity_separates_currencies(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify wallet float is reported per currency, never merged across currencies"""
    tenant = await _make_tenant(db_session, name="multi-ccy-liquidity")
    user = await _make_user(db_session, tenant)
    await _make_wallet_credit(db_session, tenant, user, amount=Decimal("500"), currency="ZAR")
    await _make_wallet_credit(db_session, tenant, user, amount=Decimal("200"), currency="MGA")

    response = await async_client.get(
        "/api/v1/analytics/liquidity",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    rows = {row["currency"]: row for row in response.json()}
    assert Decimal(rows["ZAR"]["wallet_liability"]) == Decimal("500")
    assert Decimal(rows["MGA"]["wallet_liability"]) == Decimal("200")


@pytest.mark.asyncio
async def test_net_flow_carries_currency_and_stays_separated(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify wallet inflow is reported per currency, never merged across currencies"""
    tenant = await _make_tenant(db_session, name="multi-ccy-netflow")
    user = await _make_user(db_session, tenant)
    await _make_wallet_credit(db_session, tenant, user, amount=Decimal("300"), currency="ZAR")
    await _make_wallet_credit(db_session, tenant, user, amount=Decimal("70"), currency="MGA")

    response = await async_client.get(
        "/api/v1/analytics/net-flow",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    points = response.json()
    # Every row carries a currency, and each currency's inflow stands on its own.
    inflow = {p["currency"]: Decimal(p["inflow"]) for p in points}
    assert inflow == {"ZAR": Decimal("300"), "MGA": Decimal("70")}


@pytest.mark.asyncio
async def test_metrics_timeseries_agnostic_count_per_currency_money(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the trend chart counts all transactions once but splits money by currency"""
    tenant = await _make_tenant(db_session, name="multi-ccy-timeseries")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("100"), currency="ZAR")
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("50"), currency="MGA")

    response = await async_client.get(
        "/api/v1/analytics/transactions/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Count is agnostic: both transactions summed into one dense series.
    assert sum(p["count"] for p in body["count"]["current"]) == 2
    # Volume has one series per currency, each with its own amount.
    vol = {s["currency"]: sum(Decimal(p["value"]) for p in s["current"]) for s in body["volume"]}
    assert vol == {"ZAR": Decimal("100"), "MGA": Decimal("50")}
    rev_ccys = {s["currency"] for s in body["revenue"]}
    assert rev_ccys == {"ZAR", "MGA"}


@pytest.mark.asyncio
async def test_users_by_type_groups_and_counts_each_user_type(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify the user-type breakdown counts users grouped by their type"""
    tenant = await _make_tenant(db_session, name="by-type")
    await _make_typed_user(db_session, tenant, user_type="consumer")
    await _make_typed_user(db_session, tenant, user_type="consumer")
    await _make_typed_user(db_session, tenant, user_type="agent")

    response = await async_client.get(
        "/api/v1/analytics/users/by-type",
        params={"tenant_id": str(tenant.id)},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    counts = {row["user_type"]: row["count"] for row in response.json()}
    assert counts["consumer"] == 2
    assert counts["agent"] == 1
