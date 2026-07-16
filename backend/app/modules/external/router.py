"""External partner API router (Epic 14 S4).

`POST /api/v1/external/users` — HMAC-authenticated (see auth.api_key), tenant
derived from the API key, reusing identity.create_user. Idempotent: a retry
whose identifier already maps to a user in the tenant returns that user (200)
instead of a 409, so partner retries are safe (Pay-PRD-0200).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.api_key import ApiKeyPrincipal, require_api_key
from app.database import get_async_session
from app.modules.audit.service import record_audit
from app.modules.external.schemas import (
    ExternalCreateUserRequest,
    ExternalFundRequest,
    ExternalWithdrawRequest,
)
from app.modules.external.service import external_fund, external_withdraw
from app.modules.identity.schemas import CreateUserRequest, IdentifierIn, UserOut
from app.modules.identity.service import create_user, resolve_identifier
from app.modules.treasury.schemas import FundUserResponse, WithdrawFromUserResponse
from app.shared.exceptions import IdentifierAlreadyInUse, UserNotFound
from app.shared.models import User
from app.shared.models.audit import ACTOR_SYSTEM

router = APIRouter(prefix="/api/v1/external", tags=["external"])


@router.post(
    "/users",
    response_model=UserOut,
    status_code=201,
    summary="Create a user",
    responses={
        200: {"description": "Idempotent replay — the user already existed; returned unchanged."},
        401: {"description": "Missing or invalid API key / signature."},
        422: {
            "description": "Validation error — e.g. no email/phone identifier, "
            "or a missing Idempotency-Key header."
        },
        429: {"description": "Per-key rate limit exceeded."},
    },
)
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
    # Force privilege/trust-relevant fields server-side (S7 H1): a partner gets
    # a consumer with no parent and cannot assert identifier verification.
    create_req = CreateUserRequest(
        tenant_id=principal.tenant_id,
        identifiers=[
            IdentifierIn(
                identifier_type=i.identifier_type,
                identifier_value=i.identifier_value,
                verified=False,
            )
            for i in payload.identifiers
        ],
        profile=payload.profile,
        user_type="consumer",
        parent_user_id=None,
    )
    try:
        user = await create_user(session, create_req)
        # The internal identity.create_user only audits admin-initiated creates;
        # the partner path has no admin principal, so record a system-actor
        # `user.created` row here (mirrors external_fund / external_withdraw).
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=f"apikey:{principal.key_id}",
            actor_type=ACTOR_SYSTEM,
            action="user.created",
            entity_type="user",
            entity_id=str(user.id),
            after_state={
                "identifier_count": len(create_req.identifiers),
                "has_profile": create_req.profile is not None,
                "user_type": user.user_type,
            },
        )
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


_MONEY_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid API key / signature."},
    404: {"description": "The identifier does not resolve to a user/wallet in the key's tenant."},
    409: {"description": "Insufficient funds, or nothing to withdraw (empty wallet)."},
    422: {"description": "Validation error, or a configured limit was exceeded."},
    429: {"description": "Per-key rate limit exceeded."},
}


@router.post(
    "/fund",
    response_model=FundUserResponse,
    status_code=201,
    summary="Fund a user's wallet",
    responses=_MONEY_RESPONSES,
)
async def fund_external(
    payload: ExternalFundRequest,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> FundUserResponse:
    """Credit a user's wallet in the API key's tenant.

    Tenant comes from the key, never the body. The `Idempotency-Key` header is
    required and is used as the ledger key — a retry returns the original result
    without double-crediting.
    """
    return await external_fund(
        session, principal=principal, request=payload, idempotency_key=idempotency_key
    )


@router.post(
    "/withdraw",
    response_model=WithdrawFromUserResponse,
    status_code=201,
    summary="Withdraw from a user's wallet",
    responses=_MONEY_RESPONSES,
)
async def withdraw_external(
    payload: ExternalWithdrawRequest,
    principal: ApiKeyPrincipal = Depends(require_api_key),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    session: AsyncSession = Depends(get_async_session),
) -> WithdrawFromUserResponse:
    """Debit a user's wallet in the API key's tenant.

    Send `amount`, or `withdraw_all: true` (no amount) to pull the full
    available balance. Tenant from the key; idempotent on the required
    `Idempotency-Key`.
    """
    return await external_withdraw(
        session, principal=principal, request=payload, idempotency_key=idempotency_key
    )
