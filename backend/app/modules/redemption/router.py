"""Redemption module FastAPI router.

Endpoints:
  - POST /api/v1/redemption/internal                  — points → the user's own wallet
  - GET  /api/v1/redemption/conversion-rates          — the tenant's ACTIVE rates (user)
  - GET  /api/v1/redemption/conversion-rates/admin    — every rate in a tenant (admin)

Redemption is internal-only: points are monetised into real money in the
user's own wallet at the tenant's configured rate. The provider-fulfilled
route (register / initiate / callback / confirm / fail) was removed — it was
a second, redundant way to turn points into value.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal, UserPrincipal
from app.database import get_async_session
from app.dependencies import get_current_user, require_admin_role
from app.modules.redemption.internal import initiate_internal_redemption
from app.modules.redemption.rates import list_conversion_rates
from app.modules.redemption.schemas import (
    ConversionRateOut,
    InternalRedemptionOut,
    InternalRedemptionRequest,
)

router = APIRouter(prefix="/api/v1/redemption", tags=["redemption"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


@router.get("/conversion-rates", response_model=list[ConversionRateOut])
async def get_conversion_rates(
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> list[ConversionRateOut]:
    """The tenant's ACTIVE points→fiat rates — drives the mobile redeem UI.

    Only rate-configured currencies are offered to the user (Pay-PRD-1290);
    an empty list means internal redemption is unavailable in this tenant.
    """
    rates = await list_conversion_rates(session, user.tenant_id, active_only=True)
    return [ConversionRateOut.model_validate(r) for r in rates]


@router.get("/conversion-rates/admin", response_model=list[ConversionRateOut])
async def get_conversion_rates_admin(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
) -> list[ConversionRateOut]:
    """Every conversion rate in a tenant (any status) — the admin config list.

    Mutations do NOT go through here: rates change via config change requests
    (maker-checker, config_type `conversion_rate`), like pricing/limits.
    """
    rates = await list_conversion_rates(session, tenant_id)
    return [ConversionRateOut.model_validate(r) for r in rates]


# -----------------------------------------------------------------------------
# Internal redemption (Module 11b, Pay-PRD-1200-1290)
# -----------------------------------------------------------------------------


@router.post("/internal", response_model=InternalRedemptionOut, status_code=201)
async def post_internal(
    request: InternalRedemptionRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> InternalRedemptionOut:
    """Redeem points into the user's own wallet at the configured rate.

    FAIL-CLOSED on the conversion rate (Pay-PRD-1220) and on pricing/limits
    (invariant #12). Settles synchronously — the response is the completed,
    cross-referenced points/fiat pair. Audit row recorded.
    """
    pair = await initiate_internal_redemption(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user=user,
        ip_address=_client_ip(fastapi_request),
        request=request,
        idempotency_key=idempotency_key,
    )
    return InternalRedemptionOut.model_validate(pair)
