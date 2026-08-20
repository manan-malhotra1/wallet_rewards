"""Redemption module FastAPI router (Phase F.5).

Endpoints:
  - POST /api/v1/redemption/providers                — register a provider (admin)
  - POST /api/v1/redemption/initiate                  — user-facing redemption init (user)
  - POST /api/v1/redemption/{id}/callback             — HMAC-verified provider callback
  - POST /api/v1/redemption/{id}/confirm              — admin operator override
  - POST /api/v1/redemption/{id}/fail                 — admin operator override
  - GET  /api/v1/redemption/{id}                      — status lookup (user, tenant-scoped)

Phase F.5 adds `/callback` — production provider callbacks land here with
HMAC-signed bodies. `/confirm` + `/fail` remain admin-only operator
overrides for when the provider can't or won't callback.
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
    ConfirmRedemptionRequest,
    ConversionRateOut,
    FailRedemptionRequest,
    InitiateRedemptionRequest,
    InternalRedemptionOut,
    InternalRedemptionRequest,
    ProviderOut,
    ProviderRegistrationRequest,
    RedemptionOut,
)
from app.modules.redemption.service import (
    confirm_redemption,
    fail_redemption,
    get_redemption,
    initiate_redemption,
    process_provider_callback,
    register_provider,
)

router = APIRouter(prefix="/api/v1/redemption", tags=["redemption"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing (test client)."""
    return request.client.host if request.client else None


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def post_provider(
    request: ProviderRegistrationRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ProviderOut:
    """Register a redemption provider (Pay-PRD-0730).

    Admin-only — requires `platform-admin` realm role. Auto-creates the
    associated provider_redemption_wallet account. Audit row recorded.
    """
    provider = await register_provider(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return ProviderOut.model_validate(provider)


@router.post("/initiate", response_model=RedemptionOut, status_code=201)
async def post_initiate(
    request: InitiateRedemptionRequest,
    fastapi_request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> RedemptionOut:
    """Initiate a redemption — overdraft checked, two-legged PENDING write.

    The redeeming user is the authenticated session holder — tenant_id +
    user_id come from the session token. The body carries only the
    provider + amount. Audit row recorded.
    """
    redemption = await initiate_redemption(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        user=user,
        ip_address=_client_ip(fastapi_request),
        request=request,
        idempotency_key=idempotency_key,
    )
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/callback", response_model=RedemptionOut)
async def post_callback(
    redemption_id: UUID,
    fastapi_request: Request,
    signature: str = Header(..., alias="X-Sasai-Signature", min_length=1, max_length=2048),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """HMAC-verified provider callback (Pay-PRD-0690 / 0700, Phase F.5).

    The provider POSTs a `ProviderCallbackRequest` body signed with their
    `shared_secret`. Verification happens against the RAW request body
    bytes — read here BEFORE FastAPI's Pydantic parsing. The body itself
    is parsed by the service AFTER the signature verifies, so a malformed
    JSON body can never leak existence info ahead of the HMAC check.

    No `Authorization` header is required: the HMAC IS the auth.
    """
    raw_body = await fastapi_request.body()
    redemption = await process_provider_callback(
        session,
        redemption_id=redemption_id,
        raw_body=raw_body,
        signature_header=signature,
        ip_address=_client_ip(fastapi_request),
    )
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/confirm", response_model=RedemptionOut)
async def post_confirm(
    redemption_id: UUID,
    request: ConfirmRedemptionRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Admin operator override — mark a PENDING redemption COMPLETED.

    Phase F.5: production traffic now lands at `/callback`. This endpoint
    is retained as the manual escape hatch when the provider can't /
    hasn't called back.
    """
    redemption = await confirm_redemption(
        session,
        redemption_id,
        request,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/fail", response_model=RedemptionOut)
async def post_fail(
    redemption_id: UUID,
    request: FailRedemptionRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Admin operator override — mark a PENDING redemption FAILED.

    Restores the user's points by reversing the PENDING ledger entries.
    """
    redemption = await fail_redemption(
        session,
        redemption_id,
        request,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
    return RedemptionOut.model_validate(redemption)


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


@router.get("/{redemption_id}", response_model=RedemptionOut)
async def get_redemption_route(
    redemption_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> RedemptionOut:
    """Auth-gated redemption lookup — tenant-scoped by the session token."""
    redemption = await get_redemption(session, redemption_id, user.tenant_id)
    return RedemptionOut.model_validate(redemption)


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
