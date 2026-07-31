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
    CurrencyInfo,
    CurrencyLiquidity,
    DashboardSummary,
    MetricsTimeseries,
    NetFlowPoint,
    RevenueServiceSlice,
    RewardsTimeseries,
    ServiceSlice,
    StatusBucket,
    UsersTimeseries,
    UserTypeSlice,
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


@router.get("/currencies", response_model=list[CurrencyInfo])
async def get_currencies(
    tenant_id: UUID,
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[CurrencyInfo]:
    """The tenant's spendable currencies (money instruments) for the toggle."""
    return await service.list_currencies(session, tenant_id=tenant_id)


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    tenant_id: UUID,
    range: str = Query("7d"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> DashboardSummary:
    """Headline stat-tile scalars for the range, current + previous period."""
    return await service.dashboard_summary(session, tenant_id=tenant_id, range_key=range)


@router.get("/transactions/timeseries", response_model=MetricsTimeseries)
async def get_txn_timeseries(
    tenant_id: UUID,
    range: str = Query("7d"),
    granularity: str = Query("day"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> MetricsTimeseries:
    """Agnostic count + per-currency volume & revenue, current vs previous."""
    return await service.metrics_timeseries(
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


@router.get("/revenue/by-service", response_model=list[RevenueServiceSlice])
async def get_revenue_by_service(
    tenant_id: UUID,
    range: str = Query("7d"),
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[RevenueServiceSlice]:
    """Fee/tax/commission/total grouped by service type and currency."""
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


@router.get("/liquidity", response_model=list[CurrencyLiquidity])
async def get_liquidity(
    tenant_id: UUID,
    _admin: AdminPrincipal = Depends(_require_finance_or_admin),
    session: AsyncSession = Depends(get_async_session),
) -> list[CurrencyLiquidity]:
    """Per-currency wallet float liability + cash-float balance."""
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
