"""Catalog module FastAPI router (Phase F.4 — auth-gated).

User-facing rewards view (PRD Module 16). All endpoints resolve user_id +
tenant_id from the session token via `get_current_user` — a user can only
read their own catalog data. Phase D delivered `summary`, `redemption-history`,
and `points-history`; tiers, badges, challenges, and nudges defer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user
from app.modules.catalog.schemas import (
    CatalogSummaryResponse,
    FeaturedCampaignResponse,
    PointsHistoryItem,
    RedemptionHistoryItem,
)
from app.modules.catalog.service import (
    get_featured_campaign,
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
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> list[RedemptionHistoryItem]:
    """Tenant-scoped redemption history for the session user, newest-first,
    windowed by limit/offset (B7.3 — history grows for 7 years)."""
    return await get_user_redemption_history(
        session, user.tenant_id, user.id, limit=limit, offset=offset
    )


@router.get(
    "/me/points-history",
    response_model=list[PointsHistoryItem],
)
async def get_points_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> list[PointsHistoryItem]:
    """Per-entry points ledger view (Pay-PRD-0980), newest-first, windowed by
    limit/offset (B7.3 — a points ledger grows for 7 years).

    Tenant-scoped via the user's points_account (always the session user).
    Returns `[]` when the user has no points_account in this tenant
    (consistent with the summary endpoint returning `points: null` in the
    same case).
    """
    return await get_user_points_history(
        session, user.tenant_id, user.id, limit=limit, offset=offset
    )


@router.get("/featured", response_model=FeaturedCampaignResponse)
async def get_featured(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> FeaturedCampaignResponse:
    """Single most relevant active campaign for the mobile home card (A4).

    Returns `{"campaign": null}` when no eligible campaign exists, so the
    mobile home page can collapse the slot cleanly without treating the
    empty case as an error.
    """
    campaign = await get_featured_campaign(session, tenant_id=user.tenant_id, user_id=user.id)
    return FeaturedCampaignResponse(campaign=campaign)
