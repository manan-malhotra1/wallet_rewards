"""Admin API-key management router (Epic 14 S2), platform-admin gated.

POST   /api/v1/api-keys              -> mint a key (secret shown once)
GET    /api/v1/api-keys?tenant_id=   -> list a tenant's keys (no secrets)
POST   /api/v1/api-keys/{id}/revoke  -> revoke a key (tenant-isolated)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.api_keys.schemas import ApiKeyCreatedOut, ApiKeyCreateRequest, ApiKeyOut
from app.modules.api_keys.service import create_api_key, list_api_keys, revoke_api_key

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=ApiKeyCreatedOut, status_code=201)
async def post_api_key(
    request: ApiKeyCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKeyCreatedOut:
    """Mint a key for a tenant. The plaintext secret is returned ONCE."""
    api_key, secret = await create_api_key(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    await session.commit()
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(api_key).model_dump(), secret=secret)


@router.get("", response_model=list[ApiKeyOut])
async def get_api_keys(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[ApiKeyOut]:
    """List a tenant's keys (never returns secrets)."""
    _ = admin
    keys = await list_api_keys(session, tenant_id)
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.post("/{key_pk}/revoke", response_model=ApiKeyOut)
async def post_revoke_api_key(
    key_pk: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKeyOut:
    """Revoke a key. Cross-tenant target -> 404."""
    api_key = await revoke_api_key(
        session, key_pk, tenant_id, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    await session.commit()
    return ApiKeyOut.model_validate(api_key)
