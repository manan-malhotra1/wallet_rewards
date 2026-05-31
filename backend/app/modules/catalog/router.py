"""Catalog module FastAPI router (Phase F.4 — auth-gated).

User-facing rewards view (PRD Module 16). All endpoints resolve user_id +
tenant_id from the session token via `get_current_user` — a user can only
read their own catalog data. Phase D delivered `summary`, `redemption-history`,
and `points-history`; tiers, badges, challenges, and nudges defer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user
from app.modules.catalog.schemas import (
    CatalogSummaryResponse,
    PointsHistoryItem,
    RedemptionHistoryItem,
)
from app.modules.catalog.service import (
    get_user_points_history,
    get_user_redemption_history,
    get_user_summary,
)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


@router.get("/me/summary", response_model=CatalogSummaryResponse)
async def get_summary(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> CatalogSummaryResponse:
    """Available + lifetime earned + lifetime redeemed for the session user.

    Returns `points: null` when the user has no points_account in this tenant.
    """
    return await get_user_summary(session, user.tenant_id, user.id)


@router.get(
    "/me/redemption-history",
    response_model=list[RedemptionHistoryItem],
)
async def get_redemption_history(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> list[RedemptionHistoryItem]:
    """Tenant-scoped redemption history for the session user, newest-first."""
    return await get_user_redemption_history(session, user.tenant_id, user.id)


@router.get(
    "/me/points-history",
    response_model=list[PointsHistoryItem],
)
async def get_points_history(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> list[PointsHistoryItem]:
    """Full per-entry points ledger view (Pay-PRD-0980).

    Tenant-scoped via the user's points_account (always the session user).
    Returns `[]` when the user has no points_account in this tenant
    (consistent with the summary endpoint returning `points: null` in the
    same case).
    """
    return await get_user_points_history(session, user.tenant_id, user.id)
