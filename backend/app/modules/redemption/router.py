"""Redemption module FastAPI router (Phase F.4 — auth-gated).

Endpoints:
  - POST /api/v1/redemption/providers      — register a provider (admin)
  - POST /api/v1/redemption/initiate       — user-facing redemption init (user)
  - POST /api/v1/redemption/{id}/confirm   — provider success (admin, F.5→HMAC)
  - POST /api/v1/redemption/{id}/fail      — provider failure (admin, F.5→HMAC)
  - GET  /api/v1/redemption/{id}           — status lookup (user, tenant-scoped)

Phase F.4 enforces:
  - Admin endpoints require the `platform-admin` realm role.
  - The user `/initiate` resolves user_id + tenant_id from the session token.
  - The user `/{id}` GET is auth-gated and tenant-scoped via the session.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
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
    register_provider,
)

router = APIRouter(prefix="/api/v1/redemption", tags=["redemption"])


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def post_provider(
    request: ProviderRegistrationRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ProviderOut:
    """Register a redemption provider (Pay-PRD-0730).

    Admin-only — requires `platform-admin` realm role. Auto-creates the
    associated provider_redemption_wallet account.
    """
    _ = admin  # F.5 will use admin.id for audit_log writes
    provider = await register_provider(session, request)
    return ProviderOut.model_validate(provider)


@router.post("/initiate", response_model=RedemptionOut, status_code=201)
async def post_initiate(
    request: InitiateRedemptionRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> RedemptionOut:
    """Initiate a redemption — overdraft checked, two-legged PENDING write.

    The redeeming user is the authenticated session holder — tenant_id +
    user_id come from the session token. The body carries only the
    provider + amount.
    """
    redemption = await initiate_redemption(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        request=request,
        idempotency_key=idempotency_key,
    )
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/confirm", response_model=RedemptionOut)
async def post_confirm(
    redemption_id: UUID,
    request: ConfirmRedemptionRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Mark a PENDING redemption COMPLETED (simulates provider success).

    Phase F.4: admin-gated. Phase F.5 replaces this with an HMAC-verified
    provider-callback handler (Pay-PRD-0690).
    """
    _ = admin
    redemption = await confirm_redemption(session, redemption_id, request)
    return RedemptionOut.model_validate(redemption)


@router.post("/{redemption_id}/fail", response_model=RedemptionOut)
async def post_fail(
    redemption_id: UUID,
    request: FailRedemptionRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> RedemptionOut:
    """Mark a PENDING redemption FAILED — restores the user's points.

    Phase F.4: admin-gated. Phase F.5 replaces this with HMAC-verified
    provider callback (Pay-PRD-0700).
    """
    _ = admin
    redemption = await fail_redemption(session, redemption_id, request)
    return RedemptionOut.model_validate(redemption)


@router.get("/{redemption_id}", response_model=RedemptionOut)
async def get_redemption_route(
    redemption_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: UserPrincipal = Depends(get_current_user),
) -> RedemptionOut:
    """Auth-gated redemption lookup — tenant-scoped by the session token.

    The user can only fetch redemptions in their own tenant. Cross-tenant
    access returns 404 (matches the tenant_isolation_test convention).
    """
    redemption = await get_redemption(session, redemption_id, user.tenant_id)
    return RedemptionOut.model_validate(redemption)
