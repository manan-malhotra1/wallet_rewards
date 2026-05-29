"""Identity module FastAPI router.

Phase A endpoints are TEST-ONLY — no auth. Phase 2 adds:
  - POST /otp/send, POST /otp/verify, POST /pin/set, POST /auth/pin
  - Auth dependency on every state-mutating endpoint
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.modules.identity.schemas import (
    CreateUserRequest,
    IdentifierType,
    ResolveResponse,
    UserOut,
)
from app.modules.identity.service import create_user, resolve_identifier

router = APIRouter(prefix="/api/v1/identity", tags=["identity (test-only)"])


@router.post("/users", response_model=UserOut, status_code=201)
async def post_user(
    request: CreateUserRequest,
    session: AsyncSession = Depends(get_async_session),
) -> UserOut:
    """Register a new user (TEST-ONLY — no auth in Phase A).

    Implements Pay-PRD-0010 / Pay-PRD-0050. In Phase 2 this is replaced by
    the OTP-verified registration flow.
    """
    user = await create_user(session, request)
    return UserOut.model_validate(user)


@router.get("/resolve/{identifier_type}/{identifier_value}", response_model=ResolveResponse)
async def get_resolve(
    identifier_type: IdentifierType,
    identifier_value: str,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_async_session),
) -> ResolveResponse:
    """Resolve an identifier to a canonical user_id (Pay-PRD-0060).

    `tenant_id` is a query param in Phase A because there's no auth yet.
    Phase 2 resolves tenant from the authenticated session.
    """
    row = await resolve_identifier(
        session, tenant_id, identifier_type, identifier_value
    )
    return ResolveResponse(
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        identifier_type=row.identifier_type,
    )
