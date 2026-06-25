"""Pricing module FastAPI router (Phase G.3, admin-gated)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal, UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user, require_admin_role
from app.modules.pricing.schemas import (
    FeeQuoteRequest,
    FeeQuoteResponse,
    PricingConfigCreateRequest,
    PricingConfigOut,
)
from app.modules.pricing.service import (
    create_pricing_config,
    delete_pricing_config,
    list_pricing_configs,
    quote_fee,
)

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


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


@router.post("/configs", response_model=PricingConfigOut, status_code=201)
async def post_pricing_config(
    request: PricingConfigCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> PricingConfigOut:
    """Create a per-(tenant, txn-type, account-type, currency) pricing config."""
    config = await create_pricing_config(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return PricingConfigOut.model_validate(config)


@router.get("/configs", response_model=list[PricingConfigOut])
async def get_pricing_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[PricingConfigOut]:
    """List every pricing config in a tenant."""
    _ = admin
    configs = await list_pricing_configs(session, tenant_id)
    return [PricingConfigOut.model_validate(c) for c in configs]


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pricing_config_route(
    config_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a pricing config. Cross-tenant → 404."""
    await delete_pricing_config(
        session,
        config_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
