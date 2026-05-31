"""Identity module FastAPI router.

Public endpoints (no auth) — the OTP / PIN / session flow for end-user
authentication (Phase F.2):
  - POST /otp/send, /otp/verify, /pin/set, /auth/pin, /auth/logout

Admin endpoints (require `platform-admin`) — direct user registration and
identifier resolution (Phase F.4):
  - POST /users, GET /resolve/{type}/{value}
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.auth.sessions import invalidate_session
from app.auth.tokens import extract_bearer_token
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.identity.schemas import (
    CreateUserRequest,
    IdentifierType,
    LogoutResponse,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    PinAuthRequest,
    PinSetRequest,
    ResolveResponse,
    SessionTokenResponse,
    UserOut,
)
from app.modules.identity.service import (
    authenticate_pin,
    create_user,
    resolve_identifier,
    send_otp,
    set_pin,
    verify_otp,
)

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


# =============================================================================
# Admin-only endpoints — direct user registration + identifier resolution
# =============================================================================


@router.post("/users", response_model=UserOut, status_code=201)
async def post_user(
    request: CreateUserRequest,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Directly register a user (admin-only).

    End-users register themselves via the OTP/PIN flow (/otp/send →
    /otp/verify → /pin/set). This endpoint is reserved for admin tooling
    (seeding, support recovery flows). Requires `platform-admin` role.
    """
    _ = admin  # F.5 will use admin.id for audit_log writes
    user = await create_user(session, request)
    return UserOut.model_validate(user)


@router.get(
    "/resolve/{identifier_type}/{identifier_value}",
    response_model=ResolveResponse,
)
async def get_resolve(
    identifier_type: IdentifierType,
    identifier_value: str,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ResolveResponse:
    """Resolve an identifier to a canonical user_id (Pay-PRD-0060).

    Admin-only — exposes user identity across the tenant. End-users do not
    need this endpoint (P2P resolves the recipient internally).
    """
    _ = admin
    row = await resolve_identifier(
        session, tenant_id, identifier_type, identifier_value
    )
    return ResolveResponse(
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        identifier_type=row.identifier_type,
    )


# =============================================================================
# Phase F.2 — user PIN/OTP authentication flow
# =============================================================================


@router.post("/otp/send", response_model=OtpSendResponse, status_code=202)
async def post_otp_send(
    request: OtpSendRequest,
    session: AsyncSession = Depends(get_async_session),
) -> OtpSendResponse:
    """Generate + deliver an OTP. Auto-registers unknown phones.

    Rate-limited per phone (1/60s, 5/hour). In local-dev mode the response
    body includes the OTP for tests + demos — never in production.

    PRD: Pay-PRD-0020.
    """
    return await send_otp(session, request)


@router.post("/otp/verify", response_model=OtpVerifyResponse)
async def post_otp_verify(
    request: OtpVerifyRequest,
    session: AsyncSession = Depends(get_async_session),
) -> OtpVerifyResponse:
    """Verify an OTP. Returns a short-lived registration_token for /pin/set.

    Single-use semantics — verifying the same OTP twice fails the second
    time (the used_at column is set on the first verify).

    PRD: Pay-PRD-0020.
    """
    return await verify_otp(session, request)


@router.post("/pin/set", status_code=204)
async def post_pin_set(
    request: PinSetRequest,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Set the user's PIN, authenticated by a registration_token.

    The registration_token is consumed on read — single-use.

    PRD: Pay-PRD-0030.
    """
    await set_pin(session, request)


@router.post("/auth/pin", response_model=SessionTokenResponse)
async def post_auth_pin(
    request: PinAuthRequest,
    fastapi_request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> SessionTokenResponse:
    """Authenticate with phone + PIN; issue an opaque session_token.

    Lockout enforced (NFR-0190) — `PIN_MAX_ATTEMPTS` consecutive fails →
    `PIN_LOCKOUT_MINUTES` lock window.

    PRD: Pay-PRD-0040 · NFR-0180, 0190.
    """
    # Capture caller IP for the auth_attempts row. FastAPI exposes client
    # info on the Request object; we fall back to None for tests.
    ip_address = fastapi_request.client.host if fastapi_request.client else None
    return await authenticate_pin(session, request, ip_address=ip_address)


@router.post("/auth/logout", response_model=LogoutResponse)
async def post_auth_logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> LogoutResponse:
    """Invalidate the session_token presented in the Authorization header.

    Idempotent — logging out an already-invalid token returns ok=True.
    """
    # We use extract_bearer_token but ignore the InvalidAuthorizationHeader
    # exception — logout without a token is a no-op, not an error.
    try:
        token = extract_bearer_token(authorization)
        await invalidate_session(token)
    except Exception:
        pass
    return LogoutResponse(ok=True)
