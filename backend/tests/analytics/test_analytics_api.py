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
    REWARD_TYPE_POINTS,
    TXN_STATUS_COMPLETED,
    TXN_STATUS_FAILED,
    TXN_STATUS_PENDING,
    Rule,
    RewardEvent,
    Tenant,
    Transaction,
    User,
)

# Every analytics endpoint, with the extra query params it needs beyond
# `tenant_id`. Drives the parametrised auth + empty-tenant happy-path sweeps so
# no endpoint is left uncovered.
ANALYTICS_ENDPOINTS = [
    ("/api/v1/analytics/summary", {}),
    ("/api/v1/analytics/transactions/timeseries", {"granularity": "day"}),
    ("/api/v1/analytics/transactions/by-service", {}),
    ("/api/v1/analytics/transactions/by-status", {"granularity": "day"}),
    ("/api/v1/analytics/users/timeseries", {"granularity": "day"}),
    ("/api/v1/analytics/users/active", {}),
    ("/api/v1/analytics/revenue/by-service", {}),
    ("/api/v1/analytics/rewards/timeseries", {"granularity": "day"}),
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
    initiated_by: User | None = None,
    created_at: datetime | None = None,
) -> Transaction:
    """Insert one transaction with a unique idempotency key inside the window.

    Defaults `created_at` to one day ago so the row lands inside the default 7d
    current window used by every endpoint's default `range`.
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
        currency="ZAR",
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
async def test_transactions_timeseries_is_empty_for_a_brand_new_tenant(
    async_client: AsyncClient,
    db_session: AsyncSession,
    admin_auth_header: dict[str, str],
) -> None:
    """Verify a new tenant's transaction chart returns empty current+previous series"""
    tenant = await _make_tenant(db_session, name="empty-ts")
    response = await async_client.get(
        "/api/v1/analytics/transactions/timeseries",
        params={"tenant_id": str(tenant.id), "granularity": "day"},
        headers=admin_auth_header,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"current": [], "previous": []}


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
    assert Decimal(body["transaction_volume"]["current"]) == 0

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
    assert Decimal(body["transaction_count"]["current"]) == 2
    assert Decimal(body["transaction_volume"]["current"]) == Decimal("400")
    assert Decimal(body["avg_transaction_value"]["current"]) == Decimal("200")


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
    """Verify per-service revenue sums fee, tax and commission into the total"""
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
    assert Decimal(row["total"]) == Decimal("12")


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
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("10"), initiated_by=user_one)
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("20"), initiated_by=user_one)
    await _make_txn(db_session, tenant, txn_type="cashin", amount=Decimal("30"), initiated_by=user_two)

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
