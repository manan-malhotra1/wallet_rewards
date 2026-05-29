"""Reconciliation FastAPI router — Phase E.1 test-only endpoints.

Endpoints:
  - POST /api/v1/reconciliation/sweep                  — trigger a sweep
  - GET  /api/v1/reconciliation/pending                — list stale PENDING
  - GET  /api/v1/reconciliation/manual-review          — list MANUAL_REVIEW
  - POST /api/v1/reconciliation/{redemption_id}/resolve — operator decides
  - GET  /api/v1/reconciliation/audit                  — read audit_log
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.reconciliation.schemas import (
    AuditEntry,
    ManualReviewItem,
    PendingItem,
    ResolveRequest,
    SweepOutcome,
    SweepRequest,
)
from app.modules.reconciliation.service import (
    list_manual_review,
    list_pending,
    manually_resolve,
    query_audit_log,
    sweep_pending,
)
from app.modules.redemption.schemas import RedemptionOut

router = APIRouter(
    prefix="/api/v1/reconciliation",
    tags=["reconciliation (test-only)"],
)


@router.post("/sweep", response_model=SweepOutcome)
async def post_sweep(
    request: SweepRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SweepOutcome:
    """Sweep stale PENDING redemptions — bump retry, escalate after max (Pay-PRD-0750)."""
    return await sweep_pending(
        session,
        tenant_id=request.tenant_id,
        threshold_minutes=request.threshold_minutes,
    )


@router.get("/pending", response_model=list[PendingItem])
async def get_pending(
    tenant_id: UUID,
    threshold_minutes: int = Query(default=5, ge=0, le=60 * 24 * 7),
    session: AsyncSession = Depends(get_async_session),
) -> list[PendingItem]:
    """List PENDING redemptions older than `threshold_minutes` (Pay-PRD-0750)."""
    return await list_pending(
        session, tenant_id=tenant_id, threshold_minutes=threshold_minutes
    )


@router.get("/manual-review", response_model=list[ManualReviewItem])
async def get_manual_review(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> list[ManualReviewItem]:
    """List MANUAL_REVIEW redemptions awaiting operator (Pay-PRD-0790)."""
    return await list_manual_review(session, tenant_id=tenant_id)


@router.post("/{redemption_id}/resolve", response_model=RedemptionOut)
async def post_resolve(
    redemption_id: UUID,
    request: ResolveRequest,
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Operator manually resolves a MANUAL_REVIEW redemption (Pay-PRD-0780)."""
    redemption = await manually_resolve(session, redemption_id, request)
    return RedemptionOut.model_validate(redemption)


@router.get("/audit", response_model=list[AuditEntry])
async def get_audit(
    tenant_id: UUID,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_session),
) -> list[AuditEntry]:
    """Read the audit_log, tenant-scoped, newest first."""
    return await query_audit_log(
        session,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
