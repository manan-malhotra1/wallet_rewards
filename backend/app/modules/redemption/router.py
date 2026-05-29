"""Redemption module FastAPI router (Phase D test-only endpoints).

Endpoints:
  - POST /api/v1/redemption/providers      — register a provider
  - POST /api/v1/redemption/initiate       — user-facing redemption init
  - POST /api/v1/redemption/{id}/confirm   — simulate provider success
  - POST /api/v1/redemption/{id}/fail      — simulate provider failure
  - GET  /api/v1/redemption/{id}           — status lookup
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.redemption.schemas import (
    ConfirmRedemptionRequest,
    FailRedemptionRequest,
    InitiateRedemptionRequest,
    ProviderOut,
    ProviderRegistrationRequest,
    RedemptionOut,
)
from app.modules.redemption.service import (
    confirm_redemption,
    fail_redemption,
    get_redemption,
    initiate_redemption,
    register_provider,
)

router = APIRouter(prefix="/api/v1/redemption", tags=["redemption (test-only)"])


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def post_provider(
    request: ProviderRegistrationRequest,
    session: AsyncSession = Depends(get_async_session),
) -> ProviderOut:
    """Register a redemption provider (Pay-PRD-0730).

    Auto-creates the associated provider_redemption_wallet account.
    """
    provider = await register_provider(session, request)
    return ProviderOut.model_validate(provider)


@router.post("/initiate", response_model=RedemptionOut, status_code=201)
async def post_initiate(
    request: InitiateRedemptionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Initiate a redemption — overdraft checked, two-legged PENDING write."""
    redemption = await initiate_redemption(session, request, idempotency_key)
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/confirm", response_model=RedemptionOut)
async def post_confirm(
    redemption_id: UUID,
    request: ConfirmRedemptionRequest,
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Mark a PENDING redemption COMPLETED (simulates provider success).

    Phase D: TEST-ONLY. In production this is a provider-callback handler
    with HMAC verification (Phase F).
    """
    redemption = await confirm_redemption(session, redemption_id, request)
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/fail", response_model=RedemptionOut)
async def post_fail(
    redemption_id: UUID,
    request: FailRedemptionRequest,
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Mark a PENDING redemption FAILED — restores the user's points."""
    redemption = await fail_redemption(session, redemption_id, request)
    return RedemptionOut.model_validate(redemption)


@router.get("/{redemption_id}", response_model=RedemptionOut)
async def get_redemption_route(
    redemption_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Tenant-scoped redemption lookup."""
    redemption = await get_redemption(session, redemption_id, tenant_id)
    return RedemptionOut.model_validate(redemption)
