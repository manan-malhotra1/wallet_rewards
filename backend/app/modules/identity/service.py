"""Identity service — user lifecycle and identifier resolution.

All business logic for Module 1 lives here. The router is a thin wrapper.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.schemas import (
    CreateUserRequest,
    IdentifierType,
    UserProfileIn,
)
from app.shared.exceptions import (
    IdentifierAlreadyInUse,
    TenantNotFound,
    UserNotFound,
)
from app.shared.models import (
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
