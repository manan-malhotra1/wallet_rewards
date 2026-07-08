"""External partner API router (Epic 14 S4).

`POST /api/v1/external/users` — HMAC-authenticated (see auth.api_key), tenant
derived from the API key, reusing identity.create_user. Idempotent: a retry
whose identifier already maps to a user in the tenant returns that user (200)
instead of a 409, so partner retries are safe (Pay-PRD-0200).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.api_key import ApiKeyPrincipal, require_api_key
from app.database import get_async_session
from app.modules.external.schemas import ExternalCreateUserRequest
from app.modules.identity.schemas import CreateUserRequest, UserOut
from app.modules.identity.service import create_user, resolve_identifier
from app.shared.exceptions import IdentifierAlreadyInUse, UserNotFound
from app.shared.models import User

router = APIRouter(prefix="/api/v1/external", tags=["external"])


@router.post("/users", response_model=UserOut, status_code=201)
async def create_external_user(
    payload: ExternalCreateUserRequest,
    response: Response,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Create a user in the API key's tenant, reusing the identity service.

    The tenant comes from `principal` (the key), never the body. On a retry
    that collides with an existing identifier, returns the existing user (200)
    rather than 409 — the identifier is the natural idempotency key.
    """
    create_req = CreateUserRequest(
        tenant_id=principal.tenant_id,
        identifiers=payload.identifiers,
        profile=payload.profile,
        user_type=payload.user_type,
        parent_user_id=payload.parent_user_id,
    )
    try:
        user = await create_user(session, create_req)
        await session.commit()
    except IdentifierAlreadyInUse:
        # create_user rolled back before raising; resolve the existing user.
        existing = await _existing_user(session, principal.tenant_id, payload)
        if existing is None:
            raise
        response.status_code = 200
        user = existing
    return UserOut.model_validate(user)


async def _existing_user(
    session: AsyncSession, tenant_id: UUID, payload: ExternalCreateUserRequest
) -> User | None:
    """Return the user an already-registered identifier points at, or None."""
    for ident in payload.identifiers:
        try:
            row = await resolve_identifier(
                session, tenant_id, ident.identifier_type, ident.identifier_value
            )
        except UserNotFound:
            continue
        result = await session.execute(
            select(User).options(selectinload(User.identifiers)).where(User.id == row.user_id)
        )
        return result.scalar_one()
    return None
