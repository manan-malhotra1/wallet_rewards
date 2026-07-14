"""Pricing module FastAPI router (Phase G.3, admin-gated).

Config WRITES (create/delete) are NOT exposed here — since Pricing v2 Epic 22
they go exclusively through the maker-checker flow (`/api/v1/config-requests`),
so there is no direct, single-actor path to a live pricing config. Only the
read-only fee quote and the config LIST remain.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal, UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user, require_admin_role
from app.modules.pricing.schemas import (
    FeeQuoteRequest,
    FeeQuoteResponse,
    PricingConfigOut,
)
from app.modules.pricing.service import list_pricing_configs, quote_fee

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


@router.post("/quote", response_model=FeeQuoteResponse)
async def post_fee_quote(
    request: FeeQuoteRequest,
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> FeeQuoteResponse:
    """Preview the service charge for ANY service before the user commits.

    Service-agnostic: pass the service code (p2p, cash-in, airtime_recharge,
    redemption, ...) plus amount + currency. New services need no new route —
    this single endpoint quotes them all. Read-only; tenant + sender resolve
    from the session token.

    Raises:
        InvalidSession (401): session token unknown or expired.
    """
    fee = await quote_fee(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        service=request.service,
        amount=request.amount,
        currency=request.currency,
        account_type=request.account_type,
    )
    return FeeQuoteResponse(
        service=request.service,
        amount=request.amount,
        fee=fee,
        total=request.amount + fee,
        currency=request.currency.upper(),
    )


@router.get("/configs", response_model=list[PricingConfigOut])
async def get_pricing_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[PricingConfigOut]:
    """List every pricing config in a tenant (read-only; writes go via approval)."""
    _ = admin
    configs = await list_pricing_configs(session, tenant_id)
    return [PricingConfigOut.model_validate(c) for c in configs]
