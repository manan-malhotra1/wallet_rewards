"""Limits module FastAPI router (Phase G.2, admin-gated)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.limits.schemas import LimitConfigCreateRequest, LimitConfigOut
from app.modules.limits.service import (
    create_limit_config,
    delete_limit_config,
    list_limit_configs,
)

router = APIRouter(prefix="/api/v1/limits", tags=["limits"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/configs", response_model=LimitConfigOut, status_code=201)
async def post_limit_config(
    request: LimitConfigCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> LimitConfigOut:
    """Create a per-(tenant, txn-type, account-type, currency) limit config."""
    config = await create_limit_config(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return LimitConfigOut.model_validate(config)


@router.get("/configs", response_model=list[LimitConfigOut])
async def get_limit_configs(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[LimitConfigOut]:
    """List every limit config in a tenant."""
    _ = admin
    configs = await list_limit_configs(session, tenant_id)
    return [LimitConfigOut.model_validate(c) for c in configs]


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_limit_config_route(
    config_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a limit config. Cross-tenant → 404."""
    await delete_limit_config(
        session,
        config_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
