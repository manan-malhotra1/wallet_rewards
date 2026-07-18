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

from app.auth import AdminPrincipal, UserPrincipal
from app.auth.sessions import invalidate_session
from app.auth.tokens import extract_bearer_token
from app.database import get_async_session
from app.dependencies import get_current_user, require_admin_role
from app.modules.identity.schemas import (
    AdminPinResetResponse,
    AdminUnlockResponse,
    AuthStartRequest,
    AuthStartResponse,
    ChangeUserTypeRequest,
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
    UserDetailOut,
    UserOut,
    WalletOut,
    WalletTransactionOut,
)
from app.modules.identity.service import (
    admin_reset_pin,
    admin_unlock_user,
    auth_start_lookup,
    authenticate_pin,
    change_user_type,
    create_user,
    get_my_wallet,
    get_user_detail,
    list_user_transactions,
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
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Directly register a user (admin-only).

    End-users register themselves via the OTP/PIN flow (/otp/send →
    /otp/verify → /pin/set). This endpoint is reserved for admin tooling
    (seeding, support recovery flows). Requires `platform-admin` role.
    Audit row recorded (Phase F.5, NFR-0250).
    """
    user = await create_user(
        session,
        request,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
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
    row = await resolve_identifier(session, tenant_id, identifier_type, identifier_value)
    return ResolveResponse(
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        identifier_type=row.identifier_type,
    )


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user(
    user_id: UUID,
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserDetailOut:
    """Return the full user-detail payload (admin-only).

    Includes identifiers, profile, and accounts with derived balances —
    everything the admin UI's user drawer renders. Tenant-scoped:
    requesting a user that belongs to a different tenant returns 404.
    """
    _ = admin
    payload = await get_user_detail(session, user_id=user_id, tenant_id=tenant_id)
    return UserDetailOut.model_validate(payload, from_attributes=True)


@router.patch("/users/{user_id}/type", response_model=UserOut)
async def patch_user_type(
    user_id: UUID,
    tenant_id: UUID,
    request: ChangeUserTypeRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Change a user's type (+ optional parent) — admin-only (Epic 12).

    Body: `{new_type, parent_user_id?, reason}`. `reason` is mandatory and is
    recorded in the audit log. Parent compatibility follows Decision D4.
    Tenant-scoped: a user in another tenant returns 404. Idempotent by state —
    re-issuing the same target type + parent is a no-op (no duplicate audit row).
    """
    user = await change_user_type(
        session,
        user_id=user_id,
        tenant_id=tenant_id,
        request=request,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return UserOut.model_validate(user)


@router.get(
    "/users/{user_id}/transactions",
    response_model=list[WalletTransactionOut],
)
async def get_user_transactions(
    user_id: UUID,
    tenant_id: UUID,
    limit: int = 50,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[WalletTransactionOut]:
    """Recent transactions for a user — admin user-detail page.

    Same payload shape the mobile /me/wallet feed uses, so the type +
    direction + counterparty_name logic stays in one place. Tenant-scoped:
    a user that belongs to a different tenant returns 404 (no leak).
    """
    _ = admin
    rows = await list_user_transactions(session, tenant_id=tenant_id, user_id=user_id, limit=limit)
    return [WalletTransactionOut.model_validate(r) for r in rows]


@router.post("/users/{user_id}/pin/reset", response_model=AdminPinResetResponse)
async def post_admin_pin_reset(
    user_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> AdminPinResetResponse:
    """Admin-triggered PIN reset for a user (NFR-0190 helper).

    Generates a fresh random 4-digit PIN, bcrypt-stores it on the user,
    clears any lockout state, and writes an audit row. The plaintext
    PIN is returned in the response so the operator can read it back
    over a verified channel — Phase 2 routes this through the
    notifications module for SMS delivery.

    Tenant-scoped — cross-tenant lookups return 404.
    """
    payload = await admin_reset_pin(
        session,
        user_id=user_id,
        tenant_id=tenant_id,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return AdminPinResetResponse.model_validate(payload)


@router.post("/users/{user_id}/unlock", response_model=AdminUnlockResponse)
async def post_admin_unlock(
    user_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> AdminUnlockResponse:
    """Release a user's PIN lockout WITHOUT changing their PIN (NFR-0190).

    Clears the Redis lockout + failure counter so a user locked by failed PIN
    attempts can retry immediately, keeping their existing PIN. Writes an
    `admin.user_unlocked` audit row. Tenant-scoped — cross-tenant returns 404.
    """
    payload = await admin_unlock_user(
        session,
        user_id=user_id,
        tenant_id=tenant_id,
        admin=admin,
        ip_address=fastapi_request.client.host if fastapi_request.client else None,
    )
    return AdminUnlockResponse.model_validate(payload)


# =============================================================================
# Phase F.2 — user PIN/OTP authentication flow
# =============================================================================


@router.post("/auth/start", response_model=AuthStartResponse)
async def post_auth_start(
    request: AuthStartRequest,
    session: AsyncSession = Depends(get_async_session),
) -> AuthStartResponse:
    """Branch the mobile auth flow on whether the phone is already registered.

    Pure read-only lookup — does NOT auto-register the phone (unlike
    /otp/send). The mobile client calls this immediately after the user
    enters a phone number so it can route to OTP registration
    (`needs_otp`) or PIN entry (`needs_pin`).

    Tenant-scoped: cross-tenant phone lookups return `needs_otp` so we
    don't leak existence across tenants (NFR-0220).
    """
    return await auth_start_lookup(session, request)


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


@router.get("/me/wallet", response_model=WalletOut)
async def get_me_wallet(
    user: UserPrincipal = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> WalletOut:
    """Return the authenticated user's own wallet — accounts + recent txns.

    User-facing: tenant scoping is implicit from the session token. No
    admin role required. The mobile-simulator and the eventual real
    mobile app are the primary consumers.
    """
    payload = await get_my_wallet(session, user_id=user.id, tenant_id=user.tenant_id)
    return WalletOut.model_validate(payload)
