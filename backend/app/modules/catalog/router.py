"""Catalog module FastAPI router (Phase D test-only endpoints).

User-facing rewards view (PRD Module 16). Phase D delivers `summary` and
`redemption-history`; tiers, badges, challenges, and nudges defer.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
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

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog (test-only)"])


@router.get("/{user_id}/summary", response_model=CatalogSummaryResponse)
async def get_summary(
    user_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> CatalogSummaryResponse:
    """Available + lifetime earned + lifetime redeemed for a user.

    Returns `points: null` when the user has no points_account in this tenant.
    """
    return await get_user_summary(session, tenant_id, user_id)


@router.get(
    "/{user_id}/redemption-history",
    response_model=list[RedemptionHistoryItem],
)
async def get_redemption_history(
    user_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> list[RedemptionHistoryItem]:
    """Tenant-scoped redemption history, newest-first."""
    return await get_user_redemption_history(session, tenant_id, user_id)


@router.get(
    "/{user_id}/points-history",
    response_model=list[PointsHistoryItem],
)
async def get_points_history(
    user_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> list[PointsHistoryItem]:
    """Full per-entry points ledger view (Pay-PRD-0980).

    Tenant-scoped via the user's points_account. Returns `[]` when the user
    has no points_account in this tenant (consistent with the summary
    endpoint returning `points: null` in the same case).
    """
    return await get_user_points_history(session, tenant_id, user_id)
