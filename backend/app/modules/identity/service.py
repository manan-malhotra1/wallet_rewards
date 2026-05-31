"""Identity service — user lifecycle, identifier resolution, PIN/OTP auth.

All business logic for Module 1 lives here. The router is a thin wrapper.
Phase F.2 added the OTP, PIN, and session functions at the bottom of the
file.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import hashing
from app.auth.lockout import (
    is_locked,
    lockout_seconds_remaining,
    register_failure,
    reset_failures,
)
from app.auth.rate_limit import consume_otp_send_quota
from app.auth.sessions import (
    REGTOKEN_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    consume_registration_token,
    create_registration_token,
    create_session,
)
from app.config import settings
from app.modules.identity.schemas import (
    CreateUserRequest,
    IdentifierType,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    PinAuthRequest,
    PinSetRequest,
    SessionTokenResponse,
    UserProfileIn,
)
from app.shared.exceptions import (
    AccountLocked,
    IdentifierAlreadyInUse,
    InvalidCredentials,
    InvalidOtp,
    InvalidPinFormat,
    InvalidRegistrationToken,
    OtpRateLimited,
    PinAlreadySet,
    PinNotSet,
    TenantNotFound,
    UserNotFound,
)
from app.shared.models import (
    AuthAttempt,
    OtpRequest,
    Tenant,
    User,
    UserIdentifier,
    UserProfile,
)


async def _assert_tenant_exists(session: AsyncSession, tenant_id: UUID) -> None:
    """Raise TenantNotFound if the tenant_id is not active in the DB.

    Args:
        session: Async DB session.
        tenant_id: The tenant UUID to verify.

    Raises:
        TenantNotFound: 404 when the tenant does not exist.
    """
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise TenantNotFound()


async def create_user(session: AsyncSession, request: CreateUserRequest) -> User:
    """Create a new user with one or more identifiers and optional profile.

    Tenant isolation is enforced by storing `tenant_id` on every related row.
    Identifier uniqueness is enforced by the DB constraint — we catch the
    IntegrityError and re-raise as a clean 409 (Pay-PRD-0070).

    Args:
        session: Async DB session (NOT committed here — caller commits).
        request: Validated registration payload.

    Returns:
        The created User with identifiers and profile loaded.

    Raises:
        TenantNotFound: 404 when request.tenant_id is unknown.
        IdentifierAlreadyInUse: 409 when an identifier collides in this tenant.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    user = User(tenant_id=request.tenant_id)
    session.add(user)
    # Flush to populate user.id before we insert identifiers that reference it.
    await session.flush()

    for ident in request.identifiers:
        session.add(
            UserIdentifier(
                user_id=user.id,
                tenant_id=request.tenant_id,
                identifier_type=ident.identifier_type,
                identifier_value=ident.identifier_value,
                verified=ident.verified,
            )
        )

    if request.profile is not None:
        session.add(_profile_for(user.id, request.profile))

    try:
        await session.flush()
    except IntegrityError as exc:
        # The unique constraint on (tenant_id, identifier_type, identifier_value)
        # is the only collision we expect here.
        await session.rollback()
        # We don't know which identifier collided without parsing the error —
        # the error message tells the API consumer enough.
        # Find the first colliding identifier for a clearer message.
        for ident in request.identifiers:
            existing = await _find_identifier(
                session,
                request.tenant_id,
                ident.identifier_type,
                ident.identifier_value,
            )
            if existing is not None:
                raise IdentifierAlreadyInUse(ident.identifier_type) from exc
        # Fallback if we cannot pinpoint.
        raise IdentifierAlreadyInUse(request.identifiers[0].identifier_type) from exc

    await session.commit()
    return await _reload_user(session, user.id)


def _profile_for(user_id: UUID, src: UserProfileIn) -> UserProfile:
    """Build a UserProfile row from the request fragment."""
    return UserProfile(
        user_id=user_id,
        first_name=src.first_name,
        last_name=src.last_name,
        date_of_birth=src.date_of_birth,
    )


async def _find_identifier(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: str,
    identifier_value: str,
) -> UserIdentifier | None:
    """Return the matching identifier row or None — scoped to the tenant."""
    result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.tenant_id == tenant_id,
            UserIdentifier.identifier_type == identifier_type,
            UserIdentifier.identifier_value == identifier_value,
        )
    )
    return result.scalar_one_or_none()


async def _reload_user(session: AsyncSession, user_id: UUID) -> User:
    """Fetch a user with identifiers eagerly loaded for the response."""
    result = await session.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.identifiers))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    return user


async def resolve_identifier(
    session: AsyncSession,
    tenant_id: UUID,
    identifier_type: IdentifierType,
    identifier_value: str,
) -> UserIdentifier:
    """Resolve any registered identifier to a UserIdentifier row.

    Per Pay-PRD-0060, this is the entry point that maps phone / email /
    account / card to the canonical `user_id`.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope — cross-tenant resolution is NOT supported in
            Phase 1 (PRD §6.16 non-goal).
        identifier_type: One of the supported identifier types.
        identifier_value: The raw identifier value.

    Returns:
        The matching UserIdentifier row.

    Raises:
        UserNotFound: 404 when no identifier matches in this tenant.
    """
    row = await _find_identifier(
        session, tenant_id, identifier_type, identifier_value
    )
    if row is None:
        raise UserNotFound()
    return row


# =============================================================================
# Phase F.2 — PIN/OTP user authentication flow
# =============================================================================


async def _find_user_by_phone(
    session: AsyncSession, tenant_id: UUID, phone: str
) -> User | None:
    """Resolve a phone number to a User in this tenant, or None."""
    result = await session.execute(
        select(User)
        .join(UserIdentifier, UserIdentifier.user_id == User.id)
        .where(
            User.tenant_id == tenant_id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == phone,
        )
    )
    return result.scalar_one_or_none()


async def _autocreate_user_with_phone(
    session: AsyncSession, tenant_id: UUID, phone: str
) -> User:
    """First-time user: create on-the-fly when /otp/send hits an unknown phone.

    Matches Pay-PRD-0010 semantics — registration is a side-effect of the
    first OTP for that phone.
    """
    user = User(tenant_id=tenant_id)
    session.add(user)
    await session.flush()
    session.add(
        UserIdentifier(
            user_id=user.id,
            tenant_id=tenant_id,
            identifier_type="phone",
            identifier_value=phone,
            verified=False,  # becomes True after /otp/verify
        )
    )
    await session.commit()
    await session.refresh(user)
    return user


async def send_otp(
    session: AsyncSession, request: OtpSendRequest
) -> OtpSendResponse:
    """Generate, store, and 'deliver' a one-time password.

    Auto-registers the phone if it's not already known in this tenant
    (Pay-PRD-0010). Rate-limited per phone via Redis.

    Args:
        session: Async DB session.
        request: Validated payload.

    Returns:
        Response indicating delivery; in local-dev mode the OTP itself is
        included so tests and manual demos can verify without an SMS gateway.

    Raises:
        TenantNotFound: 404 when tenant is unknown.
        OtpRateLimited: 429 when this phone has requested too many OTPs.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    allowed, retry_after = await consume_otp_send_quota(request.phone)
    if not allowed:
        raise OtpRateLimited(retry_after)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        user = await _autocreate_user_with_phone(
            session, request.tenant_id, request.phone
        )

    otp = hashing.generate_otp()
    otp_hash = hashing.hash_otp(otp)
    expires_at = datetime.now(UTC) + timedelta(
        seconds=settings.OTP_EXPIRY_SECONDS
    )
    session.add(
        OtpRequest(
            user_id=user.id,
            phone_number=request.phone,
            otp_hash=otp_hash,
            purpose="registration",
            expires_at=expires_at,
        )
    )
    await session.commit()

    return OtpSendResponse(
        delivered=True,
        otp=otp if settings.OTP_DEV_RETURN else None,
    )


async def verify_otp(
    session: AsyncSession, request: OtpVerifyRequest
) -> OtpVerifyResponse:
    """Verify an OTP, mark it used, return a short-lived registration_token.

    Single-use semantics — `used_at` is set even if the OTP value matches a
    previously-used row (defence in depth; should not happen because we
    filter on `used_at IS NULL`).

    Args:
        session: Async DB session.
        request: phone + otp.

    Returns:
        registration_token (10-min TTL in Redis) for the subsequent /pin/set.

    Raises:
        TenantNotFound: 404 when tenant_id unknown.
        InvalidOtp: 401 for wrong, expired, or already-used OTP. Same message
            for all three — no enumeration leak.
    """
    await _assert_tenant_exists(session, request.tenant_id)

    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        raise InvalidOtp()

    # Find the latest unused, unexpired OTP for this phone.
    now = datetime.now(UTC)
    result = await session.execute(
        select(OtpRequest)
        .where(
            OtpRequest.user_id == user.id,
            OtpRequest.phone_number == request.phone,
            OtpRequest.used_at.is_(None),
            OtpRequest.expires_at > now,
        )
        .order_by(OtpRequest.created_at.desc())
        .limit(1)
    )
    otp_row = result.scalar_one_or_none()
    if otp_row is None:
        raise InvalidOtp()

    if not hashing.verify_otp(request.otp, otp_row.otp_hash):
        raise InvalidOtp()

    # Mark single-use + mark identifier verified.
    otp_row.used_at = now
    identifier_result = await session.execute(
        select(UserIdentifier).where(
            UserIdentifier.user_id == user.id,
            UserIdentifier.identifier_type == "phone",
            UserIdentifier.identifier_value == request.phone,
        )
    )
    identifier = identifier_result.scalar_one_or_none()
    if identifier is not None:
        identifier.verified = True
    await session.commit()

    reg_token = await create_registration_token(user.id, request.phone)
    return OtpVerifyResponse(
        registration_token=reg_token,
        expires_in=REGTOKEN_TTL_SECONDS,
    )


def _validate_pin_format(pin: str) -> None:
    """4–6 digit numeric. Pydantic validates length; we add the digit check."""
    if not pin.isdigit():
        raise InvalidPinFormat()


async def set_pin(session: AsyncSession, request: PinSetRequest) -> None:
    """Set the user's PIN using a registration_token from /otp/verify.

    The token is single-use — `consume_registration_token` deletes it
    atomically on read.

    Args:
        session: Async DB session.
        request: registration_token + pin.

    Raises:
        InvalidPinFormat: PIN isn't 4–6 digits.
        InvalidRegistrationToken: token unknown / expired / already used.
        PinAlreadySet: user has a PIN — must use reset flow (deferred).
        UserNotFound: token's user_id doesn't exist (shouldn't happen).
    """
    _validate_pin_format(request.pin)

    payload = await consume_registration_token(request.registration_token)
    if payload is None:
        raise InvalidRegistrationToken()

    user_id = UUID(payload["user_id"])
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFound()
    if user.pin_hash is not None:
        raise PinAlreadySet()

    user.pin_hash = hashing.hash_pin(request.pin)
    await session.commit()


async def authenticate_pin(
    session: AsyncSession,
    request: PinAuthRequest,
    *,
    ip_address: str | None = None,
) -> SessionTokenResponse:
    """Verify PIN, write auth_attempts, enforce lockout, issue session_token.

    Lockout precedence:
      1. Check Redis lockout — if set, 423 immediately (don't even check PIN)
      2. Verify PIN; on miss increment counter; lock if threshold reached
      3. On success: reset counter, write success row, issue session

    Args:
        session: Async DB session.
        request: tenant + phone + PIN.
        ip_address: Caller IP for the auth_attempts row (recorded for forensics).

    Returns:
        SessionTokenResponse with the opaque token + TTL.

    Raises:
        TenantNotFound: 404 when tenant unknown.
        AccountLocked: 423 — currently locked (whether the PIN was right or not).
        InvalidCredentials: 401 — wrong phone or wrong PIN (same message).
        PinNotSet: 401 — user exists but hasn't completed PIN setup.
    """
    await _assert_tenant_exists(session, request.tenant_id)
    user = await _find_user_by_phone(session, request.tenant_id, request.phone)
    if user is None:
        raise InvalidCredentials()

    # Check lockout BEFORE comparing PIN — otherwise a locked-out attacker
    # who happens to guess the right PIN could still get in.
    if await is_locked(user.id):
        raise AccountLocked(await lockout_seconds_remaining(user.id))

    if user.pin_hash is None:
        # User started registration but never completed PIN setup.
        session.add(
            AuthAttempt(
                user_id=user.id,
                attempt_type="pin",
                success=False,
                ip_address=ip_address,
            )
        )
        await session.commit()
        raise PinNotSet()

    if not hashing.verify_pin(request.pin, user.pin_hash):
        # Record failed attempt + bump lockout counter.
        session.add(
            AuthAttempt(
                user_id=user.id,
                attempt_type="pin",
                success=False,
                ip_address=ip_address,
            )
        )
        await session.commit()
        await register_failure(user.id)
        # If the failure just tripped the lockout, prefer the locked error.
        if await is_locked(user.id):
            raise AccountLocked(await lockout_seconds_remaining(user.id))
        raise InvalidCredentials()

    # Success.
    session.add(
        AuthAttempt(
            user_id=user.id,
            attempt_type="pin",
            success=True,
            ip_address=ip_address,
        )
    )
    await session.commit()
    await reset_failures(user.id)

    session_token = await create_session(
        user_id=user.id, tenant_id=request.tenant_id, channel="mobile"
    )
    return SessionTokenResponse(
        session_token=session_token,
        expires_in=SESSION_TTL_SECONDS,
    )
