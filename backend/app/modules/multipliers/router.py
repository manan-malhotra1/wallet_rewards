"""Bonus multipliers FastAPI router (admin-gated)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminPrincipal
from app.database import get_async_session
from app.dependencies import require_admin_role
from app.modules.multipliers.schemas import (
    BonusMultiplierCreateRequest,
    BonusMultiplierOut,
)
from app.modules.multipliers.service import (
    create_multiplier,
    delete_multiplier,
    list_multipliers_for_tenant,
)

router = APIRouter(prefix="/api/v1/multipliers", tags=["multipliers"])


def _client_ip(request: Request) -> str | None:
    """Return the caller's IP, or None when missing."""
    return request.client.host if request.client else None


@router.post("", response_model=BonusMultiplierOut, status_code=201)
async def post_multiplier(
    request: BonusMultiplierCreateRequest,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> BonusMultiplierOut:
    """Create a new bonus multiplier."""
    row = await create_multiplier(
        session, request, admin=admin, ip_address=_client_ip(fastapi_request)
    )
    return BonusMultiplierOut.model_validate(row)


@router.get("", response_model=list[BonusMultiplierOut])
async def get_multipliers(
    tenant_id: UUID,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> list[BonusMultiplierOut]:
    """List every multiplier configured in the tenant."""
    _ = admin
    return await list_multipliers_for_tenant(session, tenant_id)


@router.delete("/{multiplier_id}", status_code=204)
async def remove_multiplier(
    multiplier_id: UUID,
    tenant_id: UUID,
    fastapi_request: Request,
    admin: AdminPrincipal = Depends(require_admin_role("platform-admin")),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a multiplier."""
    await delete_multiplier(
        session,
        multiplier_id,
        tenant_id,
        admin=admin,
        ip_address=_client_ip(fastapi_request),
    )
