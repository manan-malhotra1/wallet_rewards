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


@router.get("/{redemption_id}", response_model=RedemptionOut)
async def get_redemption_route(
    redemption_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> RedemptionOut:
    """Auth-gated redemption lookup — tenant-scoped by the session token."""
    redemption = await get_redemption(session, redemption_id, user.tenant_id)
    return RedemptionOut.model_validate(redemption)
